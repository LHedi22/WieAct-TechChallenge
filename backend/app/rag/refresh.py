"""REFRESH_CONTENT job (development): after a provider is picked in the UI, bring the class material
up to that provider so quizzes and notes are built from real tags and real vectors.

For every ready document:
- re-tag its chunks (CHUNK_TAG, batched, compact) when the stored tags came from a weaker provider
  (the mock's "concepts" are just its most frequent words; `documents.tagged_by`);
- embed it into the active embeddings collection (our Ollama bge-m3) when its vectors are missing
  there or its tags changed;
then queue the chapter's quiz pool again (it is regenerated only when no servable set exists).

Background lane, resumable: a Defer requeues the job and finished documents are skipped next time
(their tags are now ranked high enough and their vectors are counted). Cached class content made
by a weaker provider is not deleted: it is simply not served (core/provenance.py) and replaced the
next time it is written."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.core import db, provider_choice
from app.core.config import get_settings
from app.core.provider_choice import RANK
from app.jobs.registry import JobContext, job
from app.models import Chapter, Chunk, Course, Document
from app.rag.indexing import _tag, embed_document
from app.rag.store import get_store

log = logging.getLogger("rag")

KIND = "REFRESH_CONTENT"


async def _vectors_missing(doc: Document, n_chunks: int) -> bool:
    fixed = provider_choice.embed_provider()
    if fixed is None:  # embeddings follow the chat provider (no choice made): re-embed to be safe
        return True
    store = get_store(get_settings().profile_for(fixed))
    return await store.count({"document_id": doc.id}) < n_chunks


@job(KIND, stages=("finding_key_ideas", "saving_search_index"))
async def refresh_content(ctx: JobContext) -> dict[str, Any]:
    target = provider_choice.target()
    sm = db.get_sessionmaker()
    async with sm() as s:
        docs = list(
            await s.scalars(
                select(Document).where(Document.status == "ready").order_by(Document.created_at)
            )
        )
    retagged = embedded = 0
    chapters: set[uuid.UUID] = set()
    for doc in docs:
        async with sm() as s:
            chapter = await s.get(Chapter, doc.chapter_id)
            course = await s.get(Course, chapter.course_id)
            rows = list(
                await s.scalars(
                    select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.idx)
                )
            )
        if not rows:
            continue
        stale_tags = RANK.get(doc.tagged_by, 0) < RANK.get(target, 0)
        if stale_tags:
            await ctx.set_stage("finding_key_ideas")
            for r in rows:
                r.tags = []  # _tag skips batches that are already tagged
            await _tag(ctx, doc, course.name, chapter.title, rows)
            retagged += 1
        if stale_tags or await _vectors_missing(doc, len(rows)):
            await ctx.set_stage("saving_search_index")
            await embed_document(doc, course.name, chapter.title, rows)
            embedded += 1
        chapters.add(chapter.id)  # its pool is queued only if no servable set exists
    from app.features.quiz.pool import maybe_precompute  # noqa: PLC0415 (avoid an import cycle)

    for chapter_id in chapters:
        await maybe_precompute(chapter_id)
    log.info("refresh to %s: %d re-tagged, %d embedded", target, retagged, embedded)
    return {"provider": target, "documents": len(docs), "retagged": retagged, "embedded": embedded}
