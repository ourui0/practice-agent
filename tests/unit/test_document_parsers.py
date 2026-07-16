from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from edu_exam_agent.infrastructure.parsers import ParserRegistry


def test_text_and_markdown_are_parsed(tmp_path: Path) -> None:
    path = tmp_path / "教材.md"
    path.write_text("# 第一章\n教材内容", encoding="utf-8")
    parsed = ParserRegistry().parse(path)
    assert "教材内容" in parsed.text


def test_unknown_format_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不支持"):
        ParserRegistry().parse(tmp_path / "教材.exe")


def test_pdfium_parser_reads_pdf_pages(tmp_path: Path) -> None:
    path = tmp_path / "教材.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    with path.open("wb") as stream:
        writer.write(stream)
    parsed = ParserRegistry().parse(path)
    assert len(parsed.pages) == 1
    assert parsed.source_format == ".pdf"
    assert parsed.page_errors == 0
