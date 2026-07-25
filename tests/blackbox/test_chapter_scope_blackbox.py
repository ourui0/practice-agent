from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import ChapterModel, DocumentModel


def test_stale_flat_records_are_exposed_as_selectable_major_chapters(tmp_path: Path) -> None:
    source = tmp_path / "旧版教材解析.txt"
    source.write_text(
        "目录\n"
        "第 11 章 平面直角坐标系 ........ 1\n"
        "11.1 平面内点的坐标 ........ 2\n"
        "11.2 图形在坐标系中的平移 ........ 8\n"
        "第 12 章 函数与一次函数 ........ 23\n"
        "12.1 函数 ........ 24\n"
        "第11章 平面直角坐标系\n11.1 正文标题\n正文内容",
        encoding="utf-8",
    )
    engine = create_database_engine(tmp_path / "outline.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="黑盒测试课程"))
    with Session(engine) as session, session.begin():
        document = DocumentModel(
            course_id=course.id,
            filename=source.name,
            original_path=str(source),
            file_type=".txt",
            file_size=source.stat().st_size,
            file_hash="blackbox-outline-dataset",
            parse_status="completed",
            page_count=1,
            chapter_count=3,
        )
        session.add(document)
        session.flush()
        rows = (
            ChapterModel(
                document_id=document.id,
                title="11.1 坐标",
                position=1,
                page_start=2,
                content="正文",
            ),
            ChapterModel(
                document_id=document.id,
                title="11.2 平移",
                position=2,
                page_start=8,
                content="正文",
            ),
            ChapterModel(
                document_id=document.id,
                title="12.1 函数旧标题",
                position=3,
                page_start=24,
                content="正文",
            ),
        )
        session.add_all(rows)
        session.flush()
        document_id = document.id
        row_ids = tuple(row.id for row in rows)

    outline = DocumentService(engine).chapter_outline(document_id)

    assert [item.title for item in outline] == [
        "第11章 平面直角坐标系",
        "第12章 函数与一次函数",
    ]
    assert [section.title for section in outline[0].sections] == [
        "11.1 平面内点的坐标",
        "11.2 图形在坐标系中的平移",
    ]
    assert [section.title for section in outline[1].sections] == ["12.1 函数"]

    single_chapter_scope = outline[0].chapter_ids
    cross_chapter_scope = tuple(
        dict.fromkeys(chapter_id for item in outline for chapter_id in item.chapter_ids)
    )
    assert single_chapter_scope == row_ids[:2]
    assert cross_chapter_scope == row_ids
