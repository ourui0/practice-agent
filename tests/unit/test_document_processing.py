from __future__ import annotations

from edu_exam_agent.application.services.document_processing import (
    clean_text,
    create_chunks,
    recognize_chapters,
)
from edu_exam_agent.infrastructure.parsers import ParsedDocument, ParsedPage


def test_clean_text_normalizes_spacing() -> None:
    assert clean_text(" 标题  \r\n\r\n\r\n 正文\t内容 ") == "标题\n\n正文 内容"


def test_recognize_markdown_and_chinese_chapters() -> None:
    document = ParsedDocument(
        (
            ParsedPage(1, "# 第一章 基础\n概念内容"),
            ParsedPage(2, "第二章 应用\n应用内容"),
        ),
        source_format=".md",
    )
    chapters = recognize_chapters(document)
    assert [chapter.title for chapter in chapters] == ["第一章 基础", "第二章 应用"]
    assert chapters[1].page_start == 2


def test_chunks_never_exceed_configured_size() -> None:
    document = ParsedDocument((ParsedPage(1, "第一章 测试\n" + "内容" * 180),))
    chunks = create_chunks(recognize_chapters(document), max_chars=120)
    assert len(chunks) == 3
    assert all(chunk.character_count <= 120 for chunk in chunks)
