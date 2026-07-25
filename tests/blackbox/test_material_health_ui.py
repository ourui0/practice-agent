from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.ui.pages.material_page import MaterialPage


def test_material_page_exposes_missing_file_and_recovers_after_relink(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "material-ui.db")
    initialize_database(engine)
    courses = CourseService(engine)
    course = courses.create(CourseInput(name="沪科版八年级数学"))
    documents = DocumentService(engine)
    source = tmp_path / "【沪科版】八年级下册(2025春版)数学电子课本.md"
    source.write_text("# 第19章 四边形\n四边形教材内容。", encoding="utf-8")
    document = documents.import_document(course.id, source)
    relocated = tmp_path / "relocated" / source.name
    relocated.parent.mkdir()
    source.rename(relocated)

    page = MaterialPage(courses, documents, FtsRetriever(engine))
    page.show()
    QApplication.processEvents()
    assert page.table.rowCount() == 1
    assert "八年级" in page.table.item(0, 1).text()
    assert "下册" in page.table.item(0, 1).text()
    assert page.table.item(0, 2).text() == "文件缺失"
    assert "重新定位" in page.table.item(0, 2).toolTip()

    documents.relink_document(document.id, relocated)
    page.refresh()
    QApplication.processEvents()
    assert page.table.item(0, 2).text() == "可用"
    assert page.chapters.topLevelItemCount() == 0
    page.table.selectRow(0)
    QApplication.processEvents()
    assert page.chapters.topLevelItemCount() == 1
    page.close()
