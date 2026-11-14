"""Chapter glossary (audit OPT-11): the chapter's most frequent CHUNK_TAG concepts with the word
to use for each in the student's language, so notes, audio, tutor and grading keep one fixed form
per term. One compact TRANSLATE_SHORT call per chapter × language, shared by the class through
the gateway cache and keyed by the terms (re-tagged material gets a new glossary). No call when
the material is already in that language or has no concepts. Best effort: a failed call leaves
the prompt without a glossary."""

from __future__ import annotations

import logging
import uuid
from collections import Counter

from sqlalchemy import select

from app import gateway, prompts
from app.core import db
from app.gateway import GatewayError, Lane, Task, TaskKind
from app.gateway.cache import text_hash
from app.models import Chapter, Chunk, Course

log = logging.getLogger(__name__)

TERMS_MAX = 12
SAY_MAX = 60


async def terms(chapter_id: uuid.UUID) -> tuple[list[str], str | None]:
    """(the chapter's most frequent concepts, the material's main language)."""
    async with db.get_sessionmaker()() as s:
        rows = (
            await s.execute(
                select(Chunk.tags, Chunk.lang)
                .where(Chunk.chapter_id == chapter_id)
                .order_by(Chunk.idx)
            )
        ).all()
    counts = Counter(t for tags, _ in rows for t in tags or () if t and t != "-")
    langs = Counter(lang for _, lang in rows if lang)
    return [t for t, _ in counts.most_common(TERMS_MAX)], langs.most_common(1)[0][
        0
    ] if langs else None


def valid(content: object, asked: list[str]) -> list[tuple[str, str]]:
    """Only the terms that were asked, each once, with a short non-empty rendering."""
    items = content.get("terms") if isinstance(content, dict) else None
    out: dict[str, str] = {}
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        term, say = str(item.get("term") or "").strip(), str(item.get("say") or "").strip()
        if term in asked and term not in out and say and len(say) <= SAY_MAX:
            out[term] = say
    return [(t, out[t]) for t in asked if t in out]


def block(pairs: list[tuple[str, str]]) -> str:
    """The {glossary} text for a prompt ('' when there is nothing to say)."""
    if not pairs:
        return ""
    lines = "\n".join(f"- {term} → {say}" for term, say in pairs)
    return prompts.fragment("glossary").format(lines=lines)


async def for_chapter(chapter_id: uuid.UUID, language: str, lane: Lane) -> str:
    asked, material = await terms(chapter_id)
    if not asked or material == language:
        return ""
    async with db.get_sessionmaker()() as s:
        chapter = await s.get(Chapter, chapter_id)
        course = await s.get(Course, chapter.course_id)
    version, messages = prompts.render(
        "glossary",
        language=language,
        course=course.name,
        chapter=chapter.title,
        terms="\n".join(f"- {t}" for t in asked),
    )
    try:
        result = await gateway.run(
            Task(
                kind=TaskKind.TRANSLATE_SHORT,
                lane=lane,
                messages=messages,
                language=language,
                cache_key=f"glossary:{chapter_id}:{language}:{text_hash(chr(10).join(asked))}",
                prompt_version=version,
            )
        )
    except GatewayError as e:  # optional: the main call still runs (and meets the same limits)
        log.info("glossary skipped for %s/%s: %s", chapter_id, language, type(e).__name__)
        return ""
    # An unusable reply stays cached: asking again would be a repeated identical request (the
    # organisers' cache indicator). The chapter then has no glossary until its tags change.
    return block(valid(result.content, asked))
