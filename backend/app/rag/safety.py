"""Limits checked before any extraction (audit F-DOS-1).

DOCX and PPTX are zip archives. A tiny upload can declare parts that inflate to hundreds of MB
("zip bomb") and freeze the parser. The zip directory gives every part's declared size without
inflating anything, so we reject bombs up front. The directory can lie; the parse subprocess's
memory and time limits (`rag/indexing.py`) are the backstop."""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.rag.parsing import ParseError

TOO_COMPLEX = "errors.document_too_complex"
ARCHIVE_KINDS = ("docx", "pptx")

MAX_ENTRIES = 3000  # a 300-slide deck with media is ~1,500 parts
MAX_EXPANDED_BYTES = 150 * 1024 * 1024  # uploads are ≤ 50 MB; media barely compresses
MAX_PART_BYTES = 40 * 1024 * 1024  # a 300-page document.xml is ~10 MB
MAX_RATIO = 100  # XML compresses ~10-20×; bombs are 1000×
RATIO_MIN_BYTES = 1024 * 1024  # small parts may compress wildly; only judge big ones


def check_archive(path: Path, kind: str) -> None:
    """Raise ParseError if a DOCX/PPTX would expand beyond the limits. Other kinds pass."""
    if kind not in ARCHIVE_KINDS:
        return
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError) as e:
        raise ParseError("errors.document_unreadable") from e
    if len(infos) > MAX_ENTRIES:
        raise ParseError(TOO_COMPLEX)
    total = 0
    for info in infos:
        size = info.file_size
        total += size
        if size > MAX_PART_BYTES or total > MAX_EXPANDED_BYTES:
            raise ParseError(TOO_COMPLEX)
        if size >= RATIO_MIN_BYTES and size > MAX_RATIO * max(info.compress_size, 1):
            raise ParseError(TOO_COMPLEX)
