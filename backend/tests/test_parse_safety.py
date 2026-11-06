"""F-DOS-1 (audit 2026-11-02): one uploaded DOCX "bomb" froze every AI feature for everyone, and
a worker restart picked it up again. Uploads are now checked before extraction, parsed in a killable
subprocess with time and memory limits, a document that was mid-parse when its job died fails
instead of being retried, and /api/health reports whether the worker is alive."""

import asyncio
import sys
import time
import zipfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.jobs import heartbeat
from app.jobs.worker import Worker
from app.models import Document, Job
from app.rag import indexing
from app.rag.parsing import ParseError
from app.rag.safety import check_archive
from app.seed import samples
from tests.test_rag_indexing import gw, rag_env, upload, world_with_courses  # noqa: F401

TOO_COMPLEX = "errors.document_too_complex"


def docx_bomb(path: Path, mb: int = 60) -> Path:
    """A valid-looking DOCX whose document.xml inflates to `mb` MB from a few dozen KB."""
    para = "<w:p><w:r><w:t>" + "A" * 1000 + "</w:t></w:r></w:p>"
    body = para * (mb * 1000)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/><Override '
            'PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>' + body + "</w:body></w:document>",
        )
    return path


# --- limits checked from the zip directory, before anything is inflated --------------------------
def test_archive_check_rejects_a_bomb_and_accepts_real_files(tmp_path):
    with pytest.raises(ParseError) as e:
        check_archive(docx_bomb(tmp_path / "bomb.docx"), "docx")
    assert e.value.key == TOO_COMPLEX
    real = samples.make_all(tmp_path / "samples")
    for p in real.values():
        if p.suffix in (".docx", ".pptx"):
            check_archive(p, p.suffix[1:])  # no exception


def test_archive_check_rejects_too_many_entries(tmp_path):
    p = tmp_path / "many.pptx"
    with zipfile.ZipFile(p, "w") as z:
        for i in range(6000):
            z.writestr(f"ppt/x{i}.xml", "<a/>")
    with pytest.raises(ParseError) as e:
        check_archive(p, "pptx")
    assert e.value.key == TOO_COMPLEX


def test_archive_check_says_unreadable_for_a_non_zip(tmp_path):
    p = tmp_path / "fake.docx"
    p.write_bytes(b"not a zip at all")
    with pytest.raises(ParseError) as e:
        check_archive(p, "docx")
    assert e.value.key == "errors.document_unreadable"


# --- through the real job: the bomb fails fast and the queue keeps moving ------------------------
async def test_docx_bomb_fails_fast_and_does_not_block_the_queue(sm, gw, tmp_path):  # noqa: F811
    user, _, chapters = await world_with_courses(sm)
    bomb = docx_bomb(tmp_path / "bomb.docx")
    doc, job_id, _ = await upload(sm, user, chapters["Calculus I"], bomb)
    t0 = time.monotonic()
    await Worker(sm).drain(timeout_s=20)
    async with sm() as s:
        d = await s.get(Document, doc.id)
        j = await s.get(Job, job_id)
    assert d.status == "failed" and d.error == TOO_COMPLEX
    assert j.status == "failed" and j.error == TOO_COMPLEX
    assert time.monotonic() - t0 < 15


# --- the subprocess is killable: idle timeout and memory limit -----------------------------------
class _Doc:
    def __init__(self, path: Path) -> None:
        self.id = None
        self.kind = "txt"
        self.storage_path = str(path)


@pytest.fixture
def no_doc_updates(monkeypatch):
    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(indexing, "_update_doc", nothing)


async def test_hung_parser_is_killed_after_the_idle_timeout(monkeypatch, tmp_path, no_doc_updates):
    monkeypatch.setenv("PARSE_IDLE_TIMEOUT_S", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(
        indexing, "PARSE_CMD", [sys.executable, "-c", "import time; time.sleep(60)"]
    )
    (tmp_path / "a.txt").write_text("x")
    t0 = time.monotonic()
    with pytest.raises(ParseError) as e:
        await indexing._parse(_Doc(tmp_path / "a.txt"))
    assert e.value.key == TOO_COMPLEX
    assert time.monotonic() - t0 < 10


@pytest.mark.skipif(sys.platform == "win32", reason="memory limits use POSIX rlimits")
async def test_parser_over_the_memory_limit_is_stopped(monkeypatch, tmp_path, no_doc_updates):
    monkeypatch.setenv("PARSE_MEM_MB", "300")
    get_settings.cache_clear()
    hog = "x = bytearray(2 * 1024 ** 3); import time; time.sleep(60)"
    monkeypatch.setattr(indexing, "PARSE_CMD", [sys.executable, "-c", hog])
    (tmp_path / "a.txt").write_text("x")
    t0 = time.monotonic()
    with pytest.raises(ParseError) as e:
        await indexing._parse(_Doc(tmp_path / "a.txt"))
    assert e.value.key == TOO_COMPLEX
    assert time.monotonic() - t0 < 10


# --- a document that died mid-parse is never parsed again -----------------------------------------
async def test_document_left_mid_parse_by_a_dead_job_fails_instead_of_retrying(
    sm,
    gw,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    user, _, chapters = await world_with_courses(sm)
    f = tmp_path / "notes.txt"
    f.write_text("Limits: factor and cancel before substituting. " * 40)
    doc, job_id, _ = await upload(sm, user, chapters["Calculus I"], f)
    async with sm() as s:  # as left by a worker that died while parsing (attempt 1)
        d = await s.get(Document, doc.id)
        d.status = "parsing"
        j = await s.get(Job, job_id)
        j.attempts = 1
        await s.commit()

    def must_not_parse(*_a, **_k):
        raise AssertionError("a poison document was parsed again")

    monkeypatch.setattr(indexing, "PARSE_CMD", None)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", must_not_parse)
    await Worker(sm).drain(timeout_s=20)
    async with sm() as s:
        d = await s.get(Document, doc.id)
        j = await s.get(Job, job_id)
    assert d.status == "failed" and d.error == TOO_COMPLEX
    assert j.status == "failed"


# --- /api/health reflects whether the worker is alive ---------------------------------------------
async def test_worker_heartbeat_is_visible_to_health(sm):
    async with sm() as s:
        assert await heartbeat.worker_status(s) == ("down", None)
    engine = create_async_engine(sm.kw["bind"].url, poolclass=NullPool)  # like the worker's
    async with engine.connect() as conn:
        await heartbeat.beat(conn)
        async with sm() as s:
            status, age = await heartbeat.worker_status(s)
        assert status == "ok" and age is not None and age < 5
    await engine.dispose()
    async with sm() as s:  # the worker's connection closed: worker is down
        for _ in range(20):
            if (await heartbeat.worker_status(s))[0] == "down":
                break
            await asyncio.sleep(0.1)
        assert (await heartbeat.worker_status(s))[0] == "down"


def test_stale_heartbeat_is_reported(monkeypatch):
    now = 1_800_000_000
    names = [f"lw-worker hb={now - 300}"]
    assert heartbeat.status_from(names, now) == ("stale", 300)
    assert heartbeat.status_from([f"lw-worker hb={now - 5}"], now) == ("ok", 5)
    assert heartbeat.status_from([], now) == ("down", None)
    assert heartbeat.status_from(["psql", "lw-worker hb=garbage"], now) == ("down", None)
