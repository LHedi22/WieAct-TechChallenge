"""Rebuild one provider's vector collection from the chunks in Postgres (text is the source of
truth; vectors are per provider + embedding model).

    uv run python -m app.rag.reindex --provider cloud            # in our slot
    uv run python -m app.rag.reindex --provider local --world <id>

Embeddings go through the gateway (batched, paced, logged). A quota refusal waits the stated delay
and continues; a blocked key stops with a message (outside our slot, cloud answers 401)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

from sqlalchemy import select

from app.core.config import get_settings


async def reindex(provider: str, world_id: uuid.UUID | None) -> int:
    from app.core import db
    from app.gateway import Defer, KeyBlocked, OfflineMode
    from app.models import Chapter, Chunk, Course, Document
    from app.rag.indexing import embed_document

    sm = db.get_sessionmaker()
    async with sm() as s:
        q = select(Document).where(Document.status == "ready").order_by(Document.created_at)
        if world_id:
            q = q.where(Document.world_id == world_id)
        docs = list(await s.scalars(q))
    print(f"{len(docs)} documents to embed with provider={provider}")
    for done, doc in enumerate(docs, start=1):
        async with sm() as s:
            chapter = await s.get(Chapter, doc.chapter_id)
            course = await s.get(Course, chapter.course_id)
            rows = list(
                await s.scalars(
                    select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.idx)
                )
            )
        while True:
            try:
                used = await embed_document(doc, course.name, chapter.title, rows)
                break
            except Defer as d:
                print(f"  {d.reason}: waiting {d.delay_s:.0f}s")
                await asyncio.sleep(d.delay_s)
            except (KeyBlocked, OfflineMode):
                print("Key blocked: run this during our slot (python3 scripts/slot.py).")
                return 1
        if used != provider:  # auto fell back: never write vectors into the wrong collection
            print(f"Resolved provider is {used}, not {provider}; stopping.")
            return 1
        print(f"  [{done}/{len(docs)}] {doc.filename}: {len(rows)} chunks")
    print(f"Collection {get_settings().collection_for(get_settings().profile_for(provider))} ready")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(errors="replace")  # Windows consoles
    p = argparse.ArgumentParser(prog="python -m app.rag.reindex")
    p.add_argument("--provider", choices=["cloud", "local", "mock"], required=True)
    p.add_argument("--world", type=uuid.UUID, default=None)
    args = p.parse_args(argv)
    os.environ["LLM_PROVIDER"] = args.provider  # resolve exactly this provider's profile
    get_settings.cache_clear()
    return asyncio.run(reindex(args.provider, args.world))


if __name__ == "__main__":
    raise SystemExit(main())
