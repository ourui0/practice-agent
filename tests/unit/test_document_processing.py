from __future__ import annotations

from edu_exam_agent.application.services.document_processing import (
    clean_text,
    create_chunks,
    recognize_chapters,
    recognize_table_of_contents,
)
from edu_exam_agent.infrastructure.parsers import ParsedDocument, ParsedPage


def test_clean_text_normalizes_fullwidth_section_numbers_and_pdf_dot_glyph() -> None:
    assert clean_text("２１． １ 二次函数") == "21.1 二次函数"
    assert clean_text("２１\ue010 ２ 图象和性质") == "21.2 图象和性质"


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


def test_contents_names_drive_chapter_and_section_hierarchy() -> None:
    document = ParsedDocument(
        (
            ParsedPage(
                1,
                "目录\n第 11 章 平面直角坐标系 ........ 1\n"
                "11.1 平面内点的坐标 ........ 2\n11.2 图形在坐标系中的平移 ........ 8",
            ),
            ParsedPage(2, "第11章 平面直角坐标系\n本章导语"),
            ParsedPage(3, "11.1 坐标\n坐标正文内容"),
            ParsedPage(4, "11.2 图形平移\n平移正文内容"),
        ),
        source_format=".pdf",
    )
    toc = recognize_table_of_contents(document)
    assert toc[0].title == "第11章 平面直角坐标系"
    assert toc[0].sections == ("平面内点的坐标", "图形在坐标系中的平移")
    chapters = recognize_chapters(document)
    assert [chapter.title for chapter in chapters] == [
        "第11章 平面直角坐标系",
        "11.1 平面内点的坐标",
        "11.2 图形在坐标系中的平移",
    ]
