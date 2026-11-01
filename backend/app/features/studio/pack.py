"""The study pack: revision notes, a flashcard deck and a mind map for one chapter + level +
language, generated once and then shared by the class (cache-first).

plan-once / execute-compact: ONE mid NOTES_WRITE call from the narrowed chapter context
(narrow-before-generating, same narrowing as the quiz pool, no extra call), then two compact calls
that work only from those notes: FLASHCARDS and MAP_WRITE. Each step is saved as it lands and is
skipped on a rerun, so a Defer resumes where it stopped. The notes are the pack: without them the
job fails (coins refunded); a failed deck or map leaves the notes, and a later free run fills the
missing part."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import gateway, prompts
from app.core import db
from app.features.quiz.pool import chapter_context
from app.gateway import BadOutput, Task, TaskKind
from app.jobs.registry import JobContext, job
from app.models import Chapter, Course, Flashcard, Job, StudyAsset

KIND = "STUDY_PACK"
CARD_COUNT = 12
MIN_CARDS = 3
MAX_CARDS = 20
MIN_BRANCHES = 2
PARTS = ("notes", "flashcards", "map")


# --- validation (small models break JSON: keep what is usable, drop the rest) ----------------
class Section(BaseModel):
    heading: str = Field(min_length=1, max_length=120)
    points: list[str] = Field(min_length=1)
    refs: list[str] = []


class Term(BaseModel):
    term: str = Field(min_length=1, max_length=80)
    meaning: str = Field(min_length=1)


class Card(BaseModel):
    front: str = Field(min_length=2)
    back: str = Field(min_length=1)
    concept: str = ""


class Branch(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    children: list[str] = []


def _items(content: Any, key: str) -> list:
    raw = content.get(key) if isinstance(content, dict) else None
    return raw if isinstance(raw, list) else []


def _valid(model: type[BaseModel], raw: Any) -> BaseModel | None:
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def valid_notes(content: Any, known_refs: set[str] | None = None) -> dict[str, Any] | None:
    """Sections with at least one point; refs kept only if they name an excerpt we sent."""
    sections = []
    for raw in _items(content, "sections"):
        sec = _valid(Section, raw)
        if sec is None:
            continue
        points = [p.strip() for p in sec.points if isinstance(p, str) and p.strip()]
        refs = [r for r in sec.refs if known_refs is None or r in known_refs]
        if points:
            sections.append({"heading": sec.heading.strip(), "points": points[:6], "refs": refs})
    if not sections:
        return None
    terms = [t.model_dump() for raw in _items(content, "key_terms") if (t := _valid(Term, raw))]
    title = content.get("title") if isinstance(content.get("title"), str) else ""
    return {"title": title.strip(), "sections": sections[:8], "key_terms": terms[:10]}


def valid_cards(content: Any) -> list[dict[str, str]]:
    out, seen = [], set()
    for raw in _items(content, "cards"):
        card = _valid(Card, raw)
        if card is None or card.front.strip().lower() in seen:
            continue
        seen.add(card.front.strip().lower())
        out.append(
            {"front": card.front.strip(), "back": card.back.strip(), "concept": card.concept}
        )
    return out[:MAX_CARDS]


def valid_map(content: Any) -> dict[str, Any] | None:
    branches = []
    for raw in _items(content, "branches"):
        b = _valid(Branch, raw)
        if b is not None:
            kids = [c.strip()[:80] for c in b.children if isinstance(c, str) and c.strip()]
            branches.append({"label": b.label.strip(), "children": kids[:4]})
    root = content.get("root") if isinstance(content, dict) else None
    if not isinstance(root, str) or not root.strip() or len(branches) < MIN_BRANCHES:
        return None
    return {"root": root.strip()[:80], "branches": branches[:6]}


def notes_text(notes: dict[str, Any]) -> str:
    """The notes as plain text: the only input of the compact steps."""
    lines = [f"# {notes.get('title') or ''}".rstrip()]
    for sec in notes["sections"]:
        lines.append(f"## {sec['heading']}")
        lines += [f"- {p}" for p in sec["points"]]
    if notes.get("key_terms"):
        lines.append("## Key terms")
        lines += [f"- {t['term']}: {t['meaning']}" for t in notes["key_terms"]]
    return "\n".join(lines)


# --- what exists -------------------------------------------------------------------------------
async def assets(s, chapter_id: uuid.UUID, level: str, language: str) -> dict[str, StudyAsset]:
    rows = await s.scalars(
        select(StudyAsset).where(
            StudyAsset.chapter_id == chapter_id,
            StudyAsset.level == level,
            StudyAsset.language == language,
        )
    )
    return {a.kind: a for a in rows}


async def deck_size(s, asset_id: uuid.UUID) -> int:
    return len(list(await s.scalars(select(Flashcard.id).where(Flashcard.asset_id == asset_id))))


async def missing(s, chapter_id: uuid.UUID, level: str, language: str) -> list[str]:
    """The parts of the pack not generated yet (all three when there are no notes)."""
    found = await assets(s, chapter_id, level, language)
    if "notes" not in found:
        return list(PARTS)
    out = []
    if not await deck_size(s, found["notes"].id):
        out.append("flashcards")
    if "map" not in found:
        out.append("map")
    return out


async def pending_generation(s, chapter_id: uuid.UUID, level: str, language: str, kind: str = KIND):
    """A pack (or audio episode) already queued or running for this chapter + level + language
    (shared)."""
    return await s.scalar(
        select(Job.id).where(
            Job.kind == kind,
            Job.status.in_(("queued", "running")),
            Job.payload["chapter_id"].astext == str(chapter_id),
            Job.payload["level"].astext == level,
            Job.payload["language"].astext == language,
        )
    )


# --- the job -----------------------------------------------------------------------------------
async def save_asset(world_id, chapter_id, level, language, kind, content) -> uuid.UUID:
    async with db.get_sessionmaker()() as s:
        await s.execute(
            insert(StudyAsset)
            .values(
                id=uuid.uuid4(),
                world_id=world_id,
                chapter_id=chapter_id,
                level=level,
                language=language,
                kind=kind,
                content=content,
            )
            .on_conflict_do_nothing(index_elements=["chapter_id", "level", "language", "kind"])
        )
        await s.commit()
        return (await assets(s, chapter_id, level, language))[kind].id


def _key(ctx: JobContext, chapter: Chapter, level: str, language: str, part: str) -> str:
    """The class-wide cache is `study_assets` (a saved part is never asked again). The ai_cache key
    also carries the job, so a Defer rerun reuses a reply already paid for, while a later job,
    after a reply that failed validation, makes a fresh call instead of re-reading it."""
    return f"study:{chapter.id}:{level}:{language}:{part}:job{ctx.job_id}"


def _task(kind: TaskKind, ctx: JobContext, messages, language: str, key: str, version: str):
    return Task(
        kind=kind,
        lane=ctx.lane,
        messages=messages,
        language=language,
        cache_key=key,
        prompt_version=version,
    )


async def _notes(ctx, chapter, course, level, language) -> dict[str, Any]:
    rows = await chapter_context(ctx, chapter, course, level)
    context = "\n\n".join(f"[{c.page_ref}] {c.text}" for c in rows)
    version, messages = prompts.render(
        "notes_write",
        level=level,
        language=language,
        course=course.name,
        chapter=chapter.title,
        context=context,
    )
    key = _key(ctx, chapter, level, language, "notes")
    result = ctx.note(
        await gateway.run(_task(TaskKind.NOTES_WRITE, ctx, messages, language, key, version))
    )
    notes = valid_notes(result.content, {c.page_ref for c in rows})
    if notes is None:
        raise BadOutput("no usable notes", refusal="bad_notes")
    return notes


async def _cards(ctx, chapter, course, level, language, text: str) -> list[dict[str, str]]:
    version, messages = prompts.render(
        "flashcards",
        count=CARD_COUNT,
        level=level,
        language=language,
        course=course.name,
        chapter=chapter.title,
        notes=text,
    )
    key = _key(ctx, chapter, level, language, "flashcards")
    result = ctx.note(
        await gateway.run(_task(TaskKind.FLASHCARDS, ctx, messages, language, key, version))
    )
    cards = valid_cards(result.content)
    if len(cards) < MIN_CARDS:
        raise BadOutput(f"only {len(cards)} valid cards", refusal="bad_cards")
    return cards


async def _map(ctx, chapter, course, level, language, text: str) -> dict[str, Any]:
    version, messages = prompts.render(
        "mind_map", language=language, course=course.name, chapter=chapter.title, notes=text
    )
    key = _key(ctx, chapter, level, language, "map")
    result = ctx.note(
        await gateway.run(_task(TaskKind.MAP_WRITE, ctx, messages, language, key, version))
    )
    tree = valid_map(result.content)
    if tree is None:
        raise BadOutput("no usable mind map", refusal="bad_map")
    return tree


@job(KIND, stages=("reading_chapter", "writing_notes", "making_flashcards", "drawing_map"))
async def study_pack(ctx: JobContext) -> dict[str, Any]:
    chapter_id = uuid.UUID(ctx.payload["chapter_id"])
    level, language = ctx.payload["level"], ctx.payload["language"]
    await ctx.set_stage("reading_chapter")
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
        found = await assets(s, chapter_id, level, language)
        has_deck = "notes" in found and await deck_size(s, found["notes"].id) > 0
    world_id = course.world_id

    await ctx.set_stage("writing_notes")
    if "notes" in found:
        notes, notes_id = found["notes"].content, found["notes"].id
    else:
        notes = await _notes(ctx, chapter, course, level, language)  # failure fails the job
        notes_id = await save_asset(world_id, chapter_id, level, language, "notes", notes)
    text = notes_text(notes)

    failed: list[str] = []
    await ctx.set_stage("making_flashcards")
    if not has_deck:
        try:
            cards = await _cards(ctx, chapter, course, level, language, text)
        except gateway.Defer:
            raise
        except gateway.GatewayError:
            failed.append("flashcards")
        else:
            async with db.get_sessionmaker()() as s:
                if not await deck_size(s, notes_id):
                    s.add_all(
                        Flashcard(
                            chapter_id=chapter_id,
                            asset_id=notes_id,
                            front=c["front"],
                            back=c["back"],
                            concept=(c["concept"] or None) and c["concept"][:80],
                            source="deck",
                        )
                        for c in cards
                    )
                    await s.commit()

    await ctx.set_stage("drawing_map")
    if "map" not in found:
        try:
            tree = await _map(ctx, chapter, course, level, language, text)
        except gateway.Defer:
            raise
        except gateway.GatewayError:
            failed.append("map")
        else:
            await save_asset(world_id, chapter_id, level, language, "map", tree)
    # Public job result: what is ready; the content itself comes from GET /api/studio.
    return {"chapter_id": str(chapter_id), "level": level, "missing": failed}
