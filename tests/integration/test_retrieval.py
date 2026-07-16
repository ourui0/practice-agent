from __future__ import annotations

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def test_search_is_limited_to_course_document_and_chapter(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "retrieval.db")
    initialize_database(engine)
    courses = CourseService(engine)
    first = courses.create(CourseInput(name="课程一"))
    second = courses.create(CourseInput(name="课程二"))
    service = DocumentService(engine)
    first_file = tmp_path / "第一册.md"
    first_file.write_text(
        "# 第一章\n平行线具有丰富的几何性质。\n# 第二章\n函数知识。", encoding="utf-8"
    )
    second_file = tmp_path / "第二册.md"
    second_file.write_text("# 第一章\n平行线属于本课程的其他内容。", encoding="utf-8")
    document = service.import_document(first.id, first_file)
    service.import_document(second.id, second_file)

    retriever = FtsRetriever(engine)
    results = retriever.search("平行线", first.id)
    assert len(results) == 1
    assert results[0].document_name == "第一册.md"
    assert "平行线" in results[0].excerpt
    assert retriever.search("平行线", first.id, document_id=document.id)
    assert not retriever.search("平行线", first.id, chapter_ids=[99999])


def test_delete_document_removes_search_index(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "delete-index.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="课程"))
    material = tmp_path / "教材.txt"
    material.write_text("第一章\n勾股定理用于直角三角形。", encoding="utf-8")
    service = DocumentService(engine)
    document = service.import_document(course.id, material)
    assert FtsRetriever(engine).search("勾股定理", course.id)
    service.delete(document.id)
    assert not FtsRetriever(engine).search("勾股定理", course.id)
