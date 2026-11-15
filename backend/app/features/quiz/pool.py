"""Shared quiz sets: QUIZ_GENERATE, compact, narrow-before-generating, ONE call for 12 questions
(a set keeps 10; the extras are spares for the answer-key check, audit OPT-14).

Narrowing without an extra call: vector search in the chapter (cached query embedding of the
chapter title + level), then up to 6 chunks picked round-robin across their tagged concepts,
rotated by the set's seed so each new set looks at different material. Sets are shared by the
class: generated once per (chapter, level, language, seed), then free (economy: cached content).

Precompute after upload (M2): when a chapter's last file is ready, seed 1 at intermediate level in
the creator's language is generated on the background lane."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert

from app import gateway, prompts
from app.core import db
from app.core.provenance import replaces, servable
from app.features.quiz import verify
from app.gateway import BadOutput, Task, TaskKind
from app.gateway.cache import text_hash
from app.jobs import prefetch
from app.jobs.registry import JobContext, job
from app.jobs.service import share_key
from app.models import Chapter, Chunk, Course, Job, QuizSet
from app.rag.search import search

KIND = "QUIZ_POOL"
POOL_LEVEL = "intermediate"
POOL_SIZE = 10
GENERATE_COUNT = 12  # spares for the key check (audit OPT-14): the set keeps POOL_SIZE
# Course text per generation call (audit OPT-02): spread over the chapter up to this many
# characters (≈ 1,750 tokens), at most CONTEXT_MAX_CHUNKS chunks.
CONTEXT_CHARS = 7000
CONTEXT_MAX_CHUNKS = 24
PARTS = 3  # start, middle, end of the chapter
SEARCH_K = 12
MIN_VALID = 5


class Question(BaseModel):
    question: str = Field(min_length=3)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    hint: str = ""
    explanation: str = ""
    concept: str = ""

    @field_validator("options")
    @classmethod
    def _distinct(cls, v: list[str]) -> list[str]:
        if len({o.strip().lower() for o in v}) != 4:
            raise ValueError("options must be distinct")
        return v


def spread_answers(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move each correct option to a position picked from a hash of the question text, so the
    keys are spread over A–D (llama3.2-3b puts every answer first, 9 Nov). Deterministic, no
    model call; running it again changes nothing. The key keeps pointing at the same text."""
    for q in questions:
        opts, right = q["options"], q["answer_index"]
        target = hashlib.sha256(q["question"].encode()).digest()[0] % len(opts)
        opts[right], opts[target] = opts[target], opts[right]
        q["answer_index"] = target
    return questions


# An explanation that names another option as the answer (audit OPT-15): "the answer is B",
# "réponse (2)", "الإجابة هي ب". Checked before spread_answers moves the options.
_ANSWER_WORD = r"(?i:answer|option|choice|r[ée]ponse|choix|الإجابة|الاجابة|الجواب|الخيار)"
_LABEL = re.compile(_ANSWER_WORD + r"[^\w\n]{0,3}(?:\w+\s+){0,3}?\(?([A-D1-4]|[أبجد])\)?(?!\w)")
_LABELS = {"A": 0, "B": 1, "C": 2, "D": 3, "أ": 0, "ب": 1, "ج": 2, "د": 3}
_LABELS |= {str(i + 1): i for i in range(4)}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _mentions(text: str, option: str) -> bool:
    o = _norm(option)
    return len(o) >= 4 and re.search(rf"(?<!\w){re.escape(o)}(?!\w)", text) is not None


def contradicts(q: dict[str, Any]) -> bool:
    """The item's own explanation points at an option other than its key: it names another
    option's label, or quotes another option's text and not the key's. No model call."""
    expl, options, key = q.get("explanation") or "", q["options"], q["answer_index"]
    texts = {_norm(o) for o in options}
    for m in _LABEL.finditer(expl):
        if m.group(1).casefold() not in texts and _LABELS[m.group(1)] != key:
            return True  # a label, not an option's own text such as "4"
    text = _norm(expl)
    if _mentions(text, options[key]):
        return False
    k = _norm(options[key])
    return any(
        _mentions(text, o) and _norm(o) not in k and k not in _norm(o)
        for i, o in enumerate(options)
        if i != key
    )


def valid_questions(content: Any) -> list[dict[str, Any]]:
    raw = content.get("questions", []) if isinstance(content, dict) else []
    out = []
    for q in raw if isinstance(raw, list) else []:
        try:
            item = Question.model_validate(q).model_dump()
        except ValidationError:
            continue
        if not contradicts(item):
            out.append(item)
    return spread_answers(out)


def _concept_order(part: list[Chunk], offset: int, rank: dict[uuid.UUID, int]) -> list[Chunk]:
    """Round-robin over the part's concepts (first tag): vector hits first inside each concept,
    concepts holding a hit first; `offset` rotates which concept leads."""
    groups: dict[str, list[Chunk]] = {}
    for c in part:
        groups.setdefault(c.tags[0] if c.tags else "-", []).append(c)
    far = len(rank) + 1
    for g in groups.values():
        g.sort(key=lambda c: rank.get(c.id, far))  # stable: position breaks ties
    keys = sorted(groups, key=lambda k: rank.get(groups[k][0].id, far))
    if keys:
        r = offset % len(keys)
        keys = keys[r:] + keys[:r]
    out: list[Chunk] = []
    while any(groups[k] for k in keys):
        out += [groups[k].pop(0) for k in keys if groups[k]]
    return out


def pick_context(
    chunks: list[Chunk],
    k: int | None = None,
    offset: int = 0,
    *,
    budget_chars: int = CONTEXT_CHARS,
    prefer: list[uuid.UUID] | tuple = (),
) -> list[Chunk]:
    """The chunks a generation call sees: spread over the chapter's start, middle and end (taken
    in turn: start, end, middle, …), round-robin over concepts inside each part, up to `k` chunks
    and `budget_chars` of text. `prefer` (vector hits, best first) leads inside its part; `offset`
    rotates the concepts so a new seed looks at different material first. No model call."""
    ordered = sorted(chunks, key=lambda c: (str(c.document_id), c.idx))
    if not ordered:
        return []
    k = k or CONTEXT_MAX_CHUNKS
    rank = {cid: i for i, cid in enumerate(prefer)}
    n = len(ordered)
    parts = [ordered[i * n // PARTS : (i + 1) * n // PARTS] for i in range(PARTS)]
    turns = [_concept_order(p, offset, rank) for p in (parts[0], parts[-1], *parts[1:-1]) if p]
    picked: list[Chunk] = []
    used = 0
    while len(picked) < k and any(turns):
        for queue in turns:
            if queue and len(picked) < k:
                c = queue.pop(0)
                if used + len(c.text) <= budget_chars or not picked:
                    picked.append(c)
                    used += len(c.text)
    return sorted(picked, key=lambda c: (str(c.document_id), c.idx))


async def next_seed(s, chapter_id: uuid.UUID, level: str, language: str) -> int:
    top = await s.scalar(
        select(func.max(QuizSet.seed)).where(
            QuizSet.chapter_id == chapter_id, QuizSet.level == level, QuizSet.language == language
        )
    )
    return (top or 0) + 1


def share(chapter_id: uuid.UUID, level: str, language: str) -> str:
    """The next quiz set of a chapter + level + language, whatever seed its creator picks: one
    queued or running generation at a time, shared by the class (audit OPT-01)."""
    return share_key(KIND, chapter_id, level, language)


async def pending_generation(s, chapter_id: uuid.UUID, level: str, language: str):
    """A generation already queued or running for this chapter + level + language (shared)."""
    return await s.scalar(
        select(Job.id).where(
            Job.kind == KIND,
            Job.status.in_(("queued", "running")),
            Job.payload["chapter_id"].astext == str(chapter_id),
            Job.payload["level"].astext == level,
            Job.payload["language"].astext == language,
        )
    )


async def chapter_context(
    ctx: JobContext, chapter: Chapter, course: Course, level: str, seed: int = 1
) -> list[Chunk]:
    """narrow-before-generating without an extra call: the vector search ranks the chapter's
    chunks, pick_context spreads them over the whole chapter (shared by quiz, notes and audio)."""
    try:
        hits = await search(
            course.world_id,
            f"{chapter.title} ({level})",
            chapter_id=chapter.id,
            k=SEARCH_K,
            lane=ctx.lane,
        )
    except gateway.Defer:
        raise
    except gateway.GatewayError:
        hits = []
    async with db.get_sessionmaker()() as s:  # the whole chapter, so its end is never left out
        rows = list(await s.scalars(select(Chunk).where(Chunk.chapter_id == chapter.id)))
    return pick_context(rows, offset=seed - 1, prefer=[h.chunk_id for h in hits])


STAGES = (
    "reading_chapter",
    "matching_level",
    "writing_questions",
    "writing_hints",
    "checking_answers",
)
VERIFY_RETRY_S = 120.0  # background: wait this long for mid before checking the keys again


def shareable(questions_column):
    """SQL: every item of the set was verified (audit N-3). Unverified or legacy sets stay with
    the student who asked for them and are never handed to classmates."""
    path = literal_column("'$[*] ? (!exists(@.verified) || @.verified != true)'::jsonpath")
    return ~func.jsonb_path_exists(questions_column, path)


@job(KIND, stages=STAGES)
async def quiz_pool(ctx: JobContext) -> dict[str, Any]:
    chapter_id = uuid.UUID(ctx.payload["chapter_id"])
    level, language = ctx.payload["level"], ctx.payload["language"]
    seed = int(ctx.payload.get("seed", 1))
    await ctx.set_stage("reading_chapter")
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        existing = await s.scalar(
            select(QuizSet.id).where(
                QuizSet.chapter_id == chapter_id,
                QuizSet.level == level,
                QuizSet.language == language,
                QuizSet.seed == seed,
                servable(QuizSet.provider),
            )
        )
    if existing:
        return {"quiz_set_id": str(existing), "cached": True}
    await ctx.set_stage("matching_level")
    rows = await chapter_context(ctx, chapter, course, level, seed)
    context = "\n\n".join(f"[{c.page_ref}] {c.text}" for c in rows)
    await ctx.set_stage("writing_questions")

    async def write(salt: str = "") -> tuple[list[dict[str, Any]], Any]:
        version, messages = prompts.render(
            "quiz_generate",
            count=GENERATE_COUNT,
            level=level,
            language=language,
            course=course.name,
            chapter=chapter.title,
            context=context,
        )
        result = ctx.note(
            await gateway.run(
                Task(
                    kind=TaskKind.QUIZ_GENERATE,
                    lane=ctx.lane,
                    messages=messages,
                    language=language,
                    cache_key=f"quiz:{chapter_id}:{level}:{language}:{seed}:{text_hash(context)}{salt}",
                    prompt_version=version,
                )
            )
        )
        questions = valid_questions(result.content)
        if len(questions) < MIN_VALID:  # unusable: a retry must make a fresh call, not replay it
            await gateway.forget(result)
        return questions, result

    questions, result = await write()
    await ctx.set_stage("writing_hints")
    if len(questions) < MIN_VALID:
        raise BadOutput(f"only {len(questions)} valid questions", refusal="bad_quiz")
    # Audit N-3: no answer key reaches students unchecked (draft-then-revise).
    await ctx.set_stage("checking_answers")
    where = {"context": context, "course": course.name, "chapter": chapter.title}
    ok = await verify.check(ctx, questions, language=language, lane=ctx.lane, **where)
    if ok is None:  # mid unavailable
        if ctx.lane == "background":
            raise gateway.Defer(VERIFY_RETRY_S, "verify_unavailable")  # wait, don't publish
        questions = verify.mark_unverified(questions)[:POOL_SIZE]  # this student only, labelled
    else:
        kept = verify.keep_verified(questions, ok)
        if len(kept) < MIN_VALID and await prefetch.may_spend_mid(
            ctx.lane, ctx.payload, course.world_id
        ):  # regenerate once (a prefetch only while its mid caps leave room)
            more, _ = await write(":regen")
            ok2 = (
                await verify.check(ctx, more, language=language, lane=ctx.lane, **where)
                if more
                else None
            )
            kept += verify.keep_verified(more, ok2) if ok2 is not None else []
        if len(kept) < MIN_VALID:
            raise BadOutput(f"only {len(kept)} answer keys verified", refusal="bad_key")
        questions = kept[:POOL_SIZE]
    async with db.get_sessionmaker()() as s:
        stmt = insert(QuizSet).values(
            id=uuid.uuid4(),
            world_id=course.world_id,
            chapter_id=chapter_id,
            level=level,
            language=language,
            seed=seed,
            questions=questions,
            provider=result.provider,
        )
        await s.execute(
            stmt.on_conflict_do_update(  # a platform-made set replaces a test one (F-OFF-1)
                index_elements=["chapter_id", "level", "language", "seed"],
                set_={"questions": stmt.excluded.questions, "provider": stmt.excluded.provider},
                where=replaces(QuizSet.provider, stmt.excluded.provider),
            )
        )
        await s.commit()
        set_id = await s.scalar(
            select(QuizSet.id).where(
                QuizSet.chapter_id == chapter_id,
                QuizSet.level == level,
                QuizSet.language == language,
                QuizSet.seed == seed,
            )
        )
    # Public job result (GET /api/jobs/{id}): ids only, never questions or answers.
    return {
        "quiz_set_id": str(set_id),
        "questions": len(questions),
        "cached": result.cached,
        "verified": ok is not None,
    }
