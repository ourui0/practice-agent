from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.paper_service import PaperRequest, PaperService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import QuestionModel
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def _question(course_id: int, index: int, difficulty: int = 3) -> QuestionModel:
    return QuestionModel(
        course_id=course_id,
        question_type="填空题",
        stem=f"测试题干 {index} 是什么？",
        options_json="[]",
        answer=f"答案 {index}",
        analysis=f"这是第 {index} 题的完整解析。",
        scoring_criteria="答对得 5 分",
        knowledge_points_json='["测试知识点"]',
        difficulty=difficulty,
        estimated_time_minutes=2,
        score=5,
        quality_score=0.9,
        recommendation_score=90 - index,
        boundary_passed=True,
        status="validated",
        generation_model="mock",
    )


def test_assemble_preview_and_export(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "paper.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    with Session(engine) as session, session.begin():
        session.add_all((_question(course.id, 1, 2), _question(course.id, 2, 3)))

    service = PaperService(QuestionBankService(engine))
    paper = service.assemble(
        PaperRequest(course.id, "单元测试", ("填空题",), 2, target_difficulty=3)
    )
    assert len(paper.questions) == 2
    assert paper.questions[0].difficulty == 3
    assert paper.total_score == 10
    assert "答案 1" not in service.preview(paper)

    output = service.export_docx(paper, tmp_path / "单元测试.docx")
    assert output.exists()
    assert output.stat().st_size > 1000


def test_assemble_rejects_shortage_and_invalid_request(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "paper.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    service = PaperService(QuestionBankService(engine))

    with pytest.raises(ValueError, match="至少选择"):
        service.assemble(PaperRequest(course.id, "练习", (), 1))
    with pytest.raises(ValueError, match="只有 0 道"):
        service.assemble(PaperRequest(course.id, "练习", ("填空题",), 1))


def test_assemble_filters_by_document_and_chapter(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "scope.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    documents = DocumentService(engine)
    first_file = tmp_path / "函数.md"
    first_file.write_text("# 一次函数\n一次函数的形式是 y=kx+b。", encoding="utf-8")
    second_file = tmp_path / "几何.md"
    second_file.write_text("# 全等三角形\n全等三角形的对应边相等。", encoding="utf-8")
    first_document = documents.import_document(course.id, first_file)
    second_document = documents.import_document(course.id, second_file)

    def generate(point: str, answer: str) -> None:
        response = {
            "question_type": "填空题",
            "stem": f"请填写关于{point}的正确结论。",
            "options": [],
            "answer": answer,
            "analysis": f"依据教材中{point}的定义作答。",
            "scoring_criteria": "正确得5分",
            "knowledge_points": [point],
            "difficulty": 2,
            "estimated_time_minutes": 2,
            "score": 5,
        }
        QuestionGenerationAgent(
            engine, FtsRetriever(engine), MockProvider(response), "mock"
        ).generate(GenerationRequest(course.id, point, "填空题", 2))

    generate("一次函数", "y=kx+b")
    generate("全等三角形", "对应边相等")
    service = PaperService(QuestionBankService(engine))
    first_chapter = documents.list_chapters(first_document.id)[0]

    by_document = service.assemble(
        PaperRequest(
            course.id,
            "函数练习",
            ("填空题",),
            1,
            document_id=first_document.id,
        )
    )
    assert "一次函数" in by_document.questions[0].stem
    by_chapter = service.assemble(
        PaperRequest(
            course.id,
            "章节练习",
            ("填空题",),
            1,
            document_id=first_document.id,
            chapter_ids=(first_chapter.id,),
        )
    )
    assert by_chapter.questions[0].id == by_document.questions[0].id
    with pytest.raises(ValueError, match="只有 0 道"):
        service.assemble(
            PaperRequest(
                course.id,
                "错误范围",
                ("填空题",),
                1,
                document_id=second_document.id,
                chapter_ids=(first_chapter.id,),
            )
        )
