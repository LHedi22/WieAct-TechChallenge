"""Parsers and chunker on the synthetic sample documents (app/seed/samples.py)."""

from pathlib import Path

import pytest

from app.rag import parsing
from app.rag.chunking import CHUNK_CHARS, ChunkDraft, chunk, chunk_page
from app.rag.parsing import Page, ParseError, kind_for, parse
from app.seed import samples

needs_ocr = pytest.mark.skipif(not parsing.ocr_available(), reason="Tesseract not installed")


@pytest.fixture(scope="module")
def docs(tmp_path_factory) -> dict[str, Path]:
    return samples.make_all(tmp_path_factory.mktemp("samples"))


def test_kind_for():
    assert kind_for("Ch1.PDF") == "pdf"
    assert kind_for("notes.md") == "txt"
    assert kind_for("board.JPG") == "image"
    assert kind_for("virus.exe") is None


def test_pdf_pages_with_refs(docs):
    pages = parse(docs["pdf"], "pdf")
    assert len(pages) == 30
    assert pages[0].ref == "page:1" and pages[29].ref == "page:30"
    assert "0/0" in " ".join(p.text for p in pages[:15])
    assert "Derivatives" in pages[20].text


@needs_ocr
def test_scanned_pdf_page_goes_through_ocr(docs):
    page = parse(docs["pdf"], "pdf")[4]
    assert page.ocr and page.ref == "page:5"
    assert "Limits" in page.text


def test_pdf_scan_without_tesseract_is_skipped(docs, monkeypatch):
    monkeypatch.setattr(parsing, "tesseract_cmd", lambda: None)
    pages = parse(docs["pdf"], "pdf")
    assert len(pages) == 29 and "page:5" not in [p.ref for p in pages]


def test_pptx_slides(docs):
    pages = parse(docs["pptx"], "pptx")
    assert len(pages) == len(samples.STACK_SLIDES)
    assert pages[0].ref == "slide:1" and "LIFO" in pages[0].text


def test_docx_sections_by_heading(docs):
    pages = parse(docs["docx"], "docx")
    assert pages[0].ref == "section:1"
    assert any("chain rule" in p.text.lower() for p in pages)


def test_txt_parts(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("\n\n".join(f"Paragraph {i} " + "x" * 400 for i in range(20)), encoding="utf-8")
    pages = parse(f, "txt")
    assert len(pages) > 1 and pages[1].ref == "part:2"


def test_arabic_text_survives(tmp_path):
    f = tmp_path / "ar.txt"
    f.write_text("النهاية عندما يقترب x من 2 تساوي 4", encoding="utf-8")
    assert parse(f, "txt")[0].text.startswith("النهاية")


@needs_ocr
def test_image_ocr(docs):
    (page,) = parse(docs["png"], "image")
    assert page.ref == "image:1" and "Integrals" in page.text


def test_unreadable_pdf(tmp_path):
    f = tmp_path / "broken.pdf"
    f.write_bytes(b"not a pdf")
    with pytest.raises(ParseError) as e:
        parse(f, "pdf")
    assert e.value.key == "errors.document_unreadable"


def test_chunks_respect_size_and_never_cross_pages():
    long = "\n\n".join(f"Sentence block {i}. " + "word " * 120 for i in range(12))
    pages = [
        Page("page:1", long),
        Page("page:2", "Short second page, with enough text to be kept as a chunk."),
    ]
    drafts = chunk(pages)
    assert all(len(d.text) <= CHUNK_CHARS for d in drafts)
    assert [d.idx for d in drafts] == list(range(len(drafts)))
    assert drafts[-1] == ChunkDraft(len(drafts) - 1, pages[1].text, "page:2")
    assert {d.page_ref for d in drafts[:-1]} == {"page:1"}


def test_chunks_overlap():
    text = "\n\n".join(f"Paragraph number {i}. " + "alpha beta gamma " * 40 for i in range(6))
    a, b, *_ = chunk_page(Page("page:1", text))
    assert a[-100:].split()[-1] in b[:400]


def test_long_paragraph_is_split():
    para = " ".join(f"Sentence {i} is here." for i in range(400))
    parts = chunk_page(Page("page:1", para))
    assert len(parts) > 2 and all(len(p) <= CHUNK_CHARS for p in parts)


def test_tiny_fragments_dropped():
    assert chunk([Page("page:1", "12")]) == []


def test_sample_pdf_chunk_count(docs):
    drafts = chunk(parse(docs["pdf"], "pdf"))
    assert 25 <= len(drafts) <= 70
