from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import (
    ChapterModel,
    DocumentChunkModel,
    DocumentModel,
)


def test_import_material_creates_chapters_and_chunks(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "materials.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "教材.md"
    material.write_text(
        "# 第一章 基础\n\n" + "基础内容。" * 100 + "\n\n# 第二章 应用\n应用内容。", encoding="utf-8"
    )

    service = DocumentService(engine)
    document = service.import_document(course.id, material)
    assert document.parse_status == "completed"
    assert document.chapter_count == 2
    assert document.chunk_count >= 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ChapterModel)) == 2
        assert session.scalar(select(func.count()).select_from(DocumentChunkModel)) >= 2

    with pytest.raises(ValueError, match="已经上传"):
        service.import_document(course.id, material)


def test_delete_material_cascades_parsed_content(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "delete.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "教材.txt"
    material.write_text("第一章 内容\n正文", encoding="utf-8")
    service = DocumentService(engine)
    document = service.import_document(course.id, material)
    service.delete(document.id)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ChapterModel)) == 0


def test_parse_failure_is_persisted_for_audit(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "failed.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "教材.exe"
    material.write_text("不是教材格式", encoding="utf-8")

    with pytest.raises(ValueError, match="不支持"):
        DocumentService(engine).import_document(course.id, material)

    with Session(engine) as session:
        document = session.scalar(select(DocumentModel))
        assert document is not None
        assert document.parse_status == "failed"
        assert "不支持" in document.parse_error


def test_scanned_pdf_is_marked_as_needing_ocr(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "ocr.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="测试课程"))
    material = tmp_path / "扫描教材.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    with material.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(ValueError, match="OCR"):
        DocumentService(engine).import_document(course.id, material)
    with Session(engine) as session:
        document = session.scalar(select(DocumentModel))
        assert document is not None
        assert document.parse_status == "failed"
