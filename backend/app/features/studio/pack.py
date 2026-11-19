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
from app.core.provenance import replaces, servable
from app.features.glossary import service as glossary
from app.features.quiz.pool import chapter_context
from app.gateway import BadOutput, Task, TaskKind
from app.gateway.cache import content_key
from app.jobs import prefetch
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
            servable(StudyAsset.provider),
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
def is_quick(asset) -> bool:
    """A class asset written by the compact fallback while the mid model was saturated (audit
    F-QUICK-1): shown with a Quick-mode notice, and anyone may make the full version for free."""
    return bool(asset is not None and (asset.content or {}).get("quick_mode"))


async def save_asset(
    world_id,
    chapter_id,
    level,
    language,
    kind,
    content,
    *,
    provider: str | None,
    replace: bool = False,
) -> uuid.UUID:
    """Store a class asset once, with the provider that made it (audit F-OFF-1). `replace=True`
    overwrites it (the full version of a Quick-mode copy); a platform-made asset also replaces a
    test one. The id is kept, so the deck that hangs off the notes stays attached."""
    async with db.get_sessionmaker()() as s:
        stmt = insert(StudyAsset).values(
            id=uuid.uuid4(),
            world_id=world_id,
            chapter_id=chapter_id,
            level=level,
            language=language,
            kind=kind,
            content=content,
            provider=provider,
        )
        new = {"content": stmt.excluded.content, "provider": stmt.excluded.provider}
        stmt = stmt.on_conflict_do_update(
            index_elements=["chapter_id", "level", "language", "kind"],
            set_=new,
            where=None if replace else replaces(StudyAsset.provider, stmt.excluded.provider),
        )
        await s.execute(stmt)
        await s.commit()
        # the row under this key, whoever made it (assets() hides non-platform rows in production)
        return await s.scalar(
            select(StudyAsset.id).where(
                StudyAsset.chapter_id == chapter_id,
                StudyAsset.level == level,
                StudyAsset.language == language,
                StudyAsset.kind == kind,
            )
        )


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


async def _notes(ctx, chapter, course, level, language) -> tuple[dict[str, Any], str | None]:
    rows = await chapter_context(ctx, chapter, course, level)
    context = "\n\n".join(f"[{c.page_ref}] {c.text}" for c in rows)
    version, messages = prompts.render(
        "notes_write",
        level=level,
        language=language,
        course=course.name,
        chapter=chapter.title,
        context=context,
        glossary=await glossary.for_chapter(chapter.id, language, ctx.lane),
    )
    key = _key(ctx, chapter, level, language, "notes")
    result = ctx.note(
        await gateway.run(_task(TaskKind.NOTES_WRITE, ctx, messages, language, key, version))
    )
    notes = valid_notes(result.content, {c.page_ref for c in rows})
    if notes is None:
        raise BadOutput("no usable notes", refusal="bad_notes")
    if result.quick_mode:  # compact fallback: mark it so the class can get the mid version later
        notes = {**notes, "quick_mode": True}
    elif await prefetch.quality_pass(ctx.lane, ctx.payload, course.world_id):
        notes = await _review(ctx, chapter, course, level, language, notes, context)
    return notes, result.provider


REVIEW_MAX_FIXES = 3


async def _review(ctx, chapter, course, level, language, notes, context: str) -> dict[str, Any]:
    """Prefetch quality pass (draft-then-revise): one mid call checks the notes against the
    excerpts, the language (no stray English in Arabic or Darija, Darija not MSA) and the
    chapter's main concepts. Valid fixes replace a section's points; anything else keeps the
    notes as they are. Missing concepts are recorded on the notes, not invented."""
    concepts, _ = await glossary.terms(chapter.id)
    numbered = "\n".join(
        f"{i}. {sec['heading']}\n" + "\n".join(f"- {p}" for p in sec["points"])
        for i, sec in enumerate(notes["sections"], 1)
    )
    version, messages = prompts.render(
        "notes_review",
        level=level,
        language=language,
        course=course.name,
        chapter=chapter.title,
        concepts=", ".join(concepts) or "-",
        notes=numbered,
        context=context,
        glossary=await glossary.for_chapter(chapter.id, language, ctx.lane),
    )
    key = _key(ctx, chapter, level, language, "notes_review")
    try:
        result = ctx.note(
            await gateway.run(
                _task(TaskKind.NOTES_REVIEW, ctx, messages, language, key, version).model_copy(
                    update={"allow_fallback": False}
                )
            )
        )
    except gateway.GatewayError:  # Defer included: the notes are good enough to publish
        return notes
    return apply_review(notes, result.content)


def apply_review(notes: dict[str, Any], content: Any) -> dict[str, Any]:
    sections = [dict(sec) for sec in notes["sections"]]
    fixed = 0
    for raw in _items(content, "fixes")[:REVIEW_MAX_FIXES]:
        if not isinstance(raw, dict) or not isinstance(raw.get("section"), int):
            continue
        n, points = raw["section"], raw.get("points")
        if not 1 <= n <= len(sections) or not isinstance(points, list):
            continue
        clean = [p.strip() for p in points if isinstance(p, str) and 0 < len(p.strip()) <= 300]
        if 1 <= len(clean) <= 6:
            sections[n - 1]["points"] = clean
            fixed += 1
    missing = [m.strip()[:80] for m in _items(content, "missing") if isinstance(m, str)]
    return {**notes, "sections": sections, "review": {"fixed": fixed, "missing": missing[:8]}}


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
    if await prefetch.quality_pass(ctx.lane, ctx.payload, course.world_id):
        cards = await _check_cards(ctx, chapter, level, language, text, cards)
    return cards


async def _check_cards(ctx, chapter, level, language, text: str, cards):
    """Prefetch quality pass: one compact call names the cards the notes don't back; they are
    dropped, never below MIN_CARDS. A failed call keeps every card."""
    numbered = "\n".join(f"{i}. {c['front']} → {c['back']}" for i, c in enumerate(cards, 1))
    version, messages = prompts.render("cards_check", language=language, notes=text, cards=numbered)
    key = content_key(messages)  # notes + cards only, like the map
    try:
        result = ctx.note(
            await gateway.run(_task(TaskKind.CARDS_CHECK, ctx, messages, language, key, version))
        )
    except gateway.GatewayError:
        return cards
    bad = {n for n in _items(result.content, "unsupported") if isinstance(n, int)}
    kept = [c for i, c in enumerate(cards, 1) if i not in bad]
    return kept if len(kept) >= MIN_CARDS else cards


async def _map(ctx, chapter, course, level, language, text: str) -> dict[str, Any]:
    version, messages = prompts.render(
        "mind_map", language=language, course=course.name, chapter=chapter.title, notes=text
    )
    # Keyed by the request itself: the prompt holds only the notes, so two levels with the same
    # notes would send the same bytes (step 8, after/84). An unusable map is dropped from the
    # cache so the next job asks again.
    key = content_key(messages)
    result = ctx.note(
        await gateway.run(_task(TaskKind.MAP_WRITE, ctx, messages, language, key, version))
    )
    tree = valid_map(result.content)
    if tree is None:
        await gateway.forget(result)
        raise BadOutput("no usable mind map", refusal="bad_map")
    return tree, result.provider


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
    upgrade = "notes" in found and is_quick(found["notes"])  # the full version of a quick copy
    if "notes" in found and not upgrade:
        notes, notes_id = found["notes"].content, found["notes"].id
    else:
        notes, made_by = await _notes(ctx, chapter, course, level, language)  # fails the job
        notes_id = await save_asset(
            world_id, chapter_id, level, language, "notes", notes, provider=made_by, replace=upgrade
        )
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
            tree, made_by = await _map(ctx, chapter, course, level, language, text)
        except gateway.Defer:
            raise
        except gateway.GatewayError:
            failed.append("map")
        else:
            await save_asset(world_id, chapter_id, level, language, "map", tree, provider=made_by)
    # Public job result: what is ready; the content itself comes from GET /api/studio.
    return {"chapter_id": str(chapter_id), "level": level, "missing": failed}
