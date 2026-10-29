"""Pages → chunks of ≈500 tokens (2,000 characters; there is no tokenizer for the platform models)
with 240 characters of overlap. A chunk never spans two pages or slides, so it keeps one ref."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.parsing import Page

CHUNK_CHARS = 2000
OVERLAP_CHARS = 240
MIN_CHUNK_CHARS = 40  # drop page footers and stray numbers

_SENTENCE_END = re.compile(r"(?<=[.!?؟。])\s+")


@dataclass(frozen=True)
class ChunkDraft:
    idx: int
    text: str
    page_ref: str


def _pieces(text: str) -> list[str]:
    """Paragraphs, with paragraphs longer than one chunk split at sentence ends (or hard cut)."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= CHUNK_CHARS:
            out.append(para)
            continue
        for sentence in _SENTENCE_END.split(para):
            while len(sentence) > CHUNK_CHARS:
                out.append(sentence[:CHUNK_CHARS])
                sentence = sentence[CHUNK_CHARS - OVERLAP_CHARS :]
            if sentence.strip():
                out.append(sentence.strip())
    return out


def _tail(text: str) -> str:
    """The last ≈OVERLAP_CHARS of a chunk, starting at a word boundary."""
    if len(text) <= OVERLAP_CHARS:
        return text
    tail = text[-OVERLAP_CHARS:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < OVERLAP_CHARS // 2 else tail


def chunk_page(page: Page) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in _pieces(page.text):
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= CHUNK_CHARS:
            current = candidate
            continue
        chunks.append(current)
        current = f"{_tail(current)}\n\n{piece}"
        if len(current) > CHUNK_CHARS:  # the overlap must never push a chunk over the size
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c.strip()) >= MIN_CHUNK_CHARS]


def chunk(pages: list[Page]) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for page in pages:
        for text in chunk_page(page):
            drafts.append(ChunkDraft(len(drafts), text, page.ref))
    return drafts
