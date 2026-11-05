"""INDEX_DOCUMENT job: file → pages → chunks → CHUNK_TAG (batched, compact) → embeddings (batched)
→ Qdrant. Runs on the background lane (burst reserve at upload time).

Request economy for a 30-page PDF (~30 chunks): ⌈30/8⌉ = 4 tag calls + 1 embeddings call.
Resumable: a Defer requeues the job and every step is idempotent — chunk ids are derived from the
document id, tag batches are cached by file hash, vectors are replaced per document.

Parsing runs in a child process (`rag/parse_child.py`) with a memory limit, an idle timeout and an
overall deadline (audit F-DOS-1): a hostile or huge upload is killed instead of freezing the worker,
and a document that was mid-parse when its job died fails instead of being parsed again."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select, update

from app import gateway, prompts
from app.core import db
from app.core.config import get_settings
from app.gateway import Defer, GatewayError, Task, TaskKind
from app.jobs.registry import JobContext, job
from app.models import Chapter, Chunk, Course, Document
from app.rag.chunking import chunk
from app.rag.parsing import Page, ParseError
from app.rag.safety import TOO_COMPLEX
from app.rag.store import VectorPoint, get_store

log = logging.getLogger("rag")

KIND = "INDEX_DOCUMENT"
TAG_BATCH = 8  # chunks per CHUNK_TAG call
TAG_CHARS = 1200  # of each chunk sent for tagging (the concepts show early; keeps input small)
LEVELS = ("beginner", "intermediate", "advanced")
# progress bands on the indexing screen
P_PARSE, P_TAG, P_EMBED = 40, 75, 100
# The parse child (a module list so tests can swap it); run from the backend folder.
PARSE_CMD: list[str] | None = [sys.executable, "-m", "app.rag.parse_child"]
BACKEND_DIR = Path(__file__).resolve().parents[2]
LINE_LIMIT = 32 * 1024 * 1024  # one page of text per JSON line
# Fewer threads and malloc arenas in the parse child: keeps its memory use predictable
CHILD_ENV = {
    "MALLOC_ARENA_MAX": "2",
    "OMP_NUM_THREADS": "1",
    "OMP_THREAD_LIMIT": "1",
    "OPENBLAS_NUM_THREADS": "1",
}


class JobFailed(GatewayError):
    """A user-safe job failure with its own i18n key (unreadable file, no text…)."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.user_key = key


class ChunkTag(BaseModel):
    id: str
    concepts: list[str] = Field(default_factory=list)
    level: str | None = None
    lang: str | None = None


class TagReply(BaseModel):
    chunks: list[ChunkTag]


def chunk_uuid(document_id: uuid.UUID, idx: int) -> uuid.UUID:
    return uuid.uuid5(document_id, f"chunk:{idx}")


def upload_path(doc: Document) -> Path:
    path = Path(doc.storage_path)
    return path if path.is_absolute() else Path(get_settings().UPLOAD_DIR) / path


UNIT = {"pdf": "page", "pptx": "slide", "docx": "section", "txt": "part", "image": "image"}


async def _update_doc(doc_id: uuid.UUID, **values: Any) -> None:
    async with db.get_sessionmaker()() as s:
        await s.execute(update(Document).where(Document.id == doc_id).values(**values))
        await s.commit()


async def _parse(doc: Document) -> list[Page]:
    """Parse in a killable child process; any limit breach is `errors.document_too_complex`."""
    settings = get_settings()
    unit = UNIT[doc.kind]
    # The memory limit is set inside the child by a launcher that then exec()s the parser:
    # preexec_fn would be simpler but can deadlock when the worker has threads.
    limited = [sys.executable, "-m", "app.rag.limit_exec", str(settings.PARSE_MEM_MB)]
    proc = await asyncio.create_subprocess_exec(
        *(limited if os.name == "posix" else []),
        *PARSE_CMD,
        str(upload_path(doc)),
        doc.kind,
        stdout=asyncio.subprocess.PIPE,
        cwd=str(BACKEND_DIR),
        env={**os.environ, **CHILD_ENV},
        limit=LINE_LIMIT,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.PARSE_MAX_S
    pages: list[Page] = []
    total, done = 1, False
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            line = await asyncio.wait_for(
                proc.stdout.readline(), min(settings.PARSE_IDLE_TIMEOUT_S, remaining)
            )
            if not line:
                break
            msg = json.loads(line)
            if "error" in msg:
                raise ParseError(msg["error"])
            if "total" in msg:
                total = max(int(msg["total"]), 1)
                continue
            if msg.get("done"):
                done = True
                continue
            n = int(msg["n"])
            if msg.get("page"):
                pages.append(Page(**msg["page"]))
            await _update_doc(
                doc.id,
                progress=int(P_PARSE * n / total),
                detail={"key": unit, "n": n, "of": total},
                page_count=total,
            )
        if await proc.wait() != 0 or not done:
            raise ParseError(TOO_COMPLEX)  # killed by the memory limit, crashed, or cut short
    except (TimeoutError, ValueError, KeyError, TypeError) as e:
        log.warning("parse of document %s stopped: %s", doc.id, type(e).__name__)
        raise ParseError(TOO_COMPLEX) from e
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return pages


def _clean_tags(tag: ChunkTag | None) -> tuple[list[str], str | None, str | None]:
    if tag is None:
        return [], None, None
    concepts = [c.strip()[:64] for c in tag.concepts if c and c.strip()][:5]
    level = tag.level if tag.level in LEVELS else None
    lang = (tag.lang or "")[:8] or None
    return concepts, level, lang


async def _tag(ctx: JobContext, doc: Document, course: str, chapter: str, rows: list[Chunk]):
    batches = [rows[i : i + TAG_BATCH] for i in range(0, len(rows), TAG_BATCH)]
    for b, batch in enumerate(batches):
        if all(r.tags for r in batch):
            continue  # tagged before a Defer
        text = "\n\n".join(f"[[chunk:c{r.idx}]] {r.text[:TAG_CHARS]}" for r in batch)
        version, messages = prompts.render("chunk_tag", course=course, chapter=chapter, chunks=text)
        result = ctx.note(
            await gateway.run(
                Task(
                    kind=TaskKind.CHUNK_TAG,
                    lane="background",
                    messages=messages,
                    language="en",
                    # same file → same chunks → same tags, whichever world uploads it
                    cache_key=f"{doc.sha256}:{TAG_BATCH}:{b}",
                    prompt_version=version,
                )
            )
        )
        try:
            tags = {t.id: t for t in TagReply.model_validate(result.content).chunks}
        except ValidationError:
            log.warning("CHUNK_TAG reply did not validate; chunks stay untagged")
            tags = {}
        async with db.get_sessionmaker()() as s:
            for r in batch:
                concepts, level, lang = _clean_tags(tags.get(f"c{r.idx}"))
                r.tags, r.level, r.lang = concepts or ["-"], level, lang
                await s.execute(
                    update(Chunk)
                    .where(Chunk.id == r.id)
                    .values(tags=r.tags, level=r.level, lang=r.lang)
                )
            await s.commit()
        progress = P_PARSE + int((P_TAG - P_PARSE) * (b + 1) / len(batches))
        await _update_doc(doc.id, progress=progress, detail={"key": "ideas", "n": b + 1})


async def embed_document(doc: Document, course: str, chapter: str, rows: list[Chunk]) -> str:
    # The course and chapter titles help retrieval; the stored text stays the chunk itself.
    texts = [f"{course} · {chapter}\n{r.text}" for r in rows]
    res = await gateway.embed(texts, "background")
    store = get_store(get_settings().profile_for(res.provider))
    await store.delete_document(doc.id)
    await store.upsert(
        [
            VectorPoint(
                r.id,
                vec,
                {
                    "world_id": str(r.world_id),
                    "course_id": str(r.course_id),
                    "chapter_id": str(r.chapter_id),
                    "document_id": str(r.document_id),
                    "level_tags": [r.level or "intermediate"],
                    "tags": [t for t in r.tags if t != "-"],
                    "page_ref": r.page_ref,
                    "lang": r.lang,
                },
            )
            for r, vec in zip(rows, res.vectors, strict=True)
        ]
    )
    return res.provider


@job(KIND, stages=("parsing_file", "reading_pages", "finding_key_ideas", "saving_search_index"))
async def index_document(ctx: JobContext) -> dict[str, Any]:
    doc_id = uuid.UUID(ctx.payload["document_id"])
    sm = db.get_sessionmaker()
    async with sm() as s:
        doc = await s.get(Document, doc_id)
        if doc is None:
            raise JobFailed("errors.document_not_found")
        chapter = await s.get(Chapter, doc.chapter_id)
        course = await s.get(Course, chapter.course_id)
        rows = list(
            await s.scalars(select(Chunk).where(Chunk.document_id == doc_id).order_by(Chunk.idx))
        )
    if doc.status == "ready":
        return {"document_id": str(doc_id), "chunks": len(rows), "status": "ready"}
    if doc.status == "parsing" and not rows and ctx.attempts > 1:
        # A previous attempt died while parsing this file (worker crash, OOM): never parse it
        # again, or one poison upload stalls the queue after every restart.
        await _update_doc(doc_id, status="failed", error=TOO_COMPLEX, detail=None)
        raise JobFailed(TOO_COMPLEX)

    status: Literal["parsing", "tagging", "embedding"] = "parsing"
    try:
        if not rows:  # (re)parse unless chunks survived a Defer
            await ctx.set_stage("parsing_file")
            await _update_doc(doc_id, status="parsing", error=None, progress=0)
            await ctx.set_stage("reading_pages")
            pages = await _parse(doc)
            drafts = chunk(pages)
            if not drafts:
                raise JobFailed("errors.document_empty")
            rows = [
                Chunk(
                    id=chunk_uuid(doc_id, d.idx),
                    document_id=doc_id,
                    chapter_id=chapter.id,
                    course_id=course.id,
                    world_id=doc.world_id,
                    idx=d.idx,
                    text=d.text,
                    page_ref=d.page_ref,
                    tags=[],
                )
                for d in drafts
            ]
            async with sm() as s:
                await s.execute(delete(Chunk).where(Chunk.document_id == doc_id))
                s.add_all(rows)
                await s.commit()

        status = "tagging"
        await ctx.set_stage("finding_key_ideas")
        await _update_doc(doc_id, status=status)
        await _tag(ctx, doc, course.name, chapter.title, rows)

        status = "embedding"
        await ctx.set_stage("saving_search_index")
        await _update_doc(doc_id, status=status, detail={"key": "saving"})
        provider = await embed_document(doc, course.name, chapter.title, rows)
    except Defer:
        await _update_doc(doc_id, status=status, detail={"key": "waiting"})
        raise
    except ParseError as e:
        await _update_doc(doc_id, status="failed", error=e.key, detail=None)
        raise JobFailed(e.key) from e
    except GatewayError as e:
        await _update_doc(doc_id, status="failed", error=e.user_key, detail=None)
        raise
    except Exception:
        await _update_doc(doc_id, status="failed", error="errors.indexing_failed", detail=None)
        raise

    await _update_doc(doc_id, status="ready", progress=P_EMBED, detail=None, error=None)
    from app.features.quiz.pool import maybe_precompute  # noqa: PLC0415 (avoid an import cycle)

    await maybe_precompute(chapter.id)
    return {"document_id": str(doc_id), "chunks": len(rows), "provider": provider}
