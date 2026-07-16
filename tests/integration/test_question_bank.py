from __future__ import annotations

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.application.services.question_bank_service import (
    QuestionBankService,
    QuestionEdit,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def test_question_bank_filter_edit_version_duplicate_delete(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "bank.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 一次函数\n一次函数形式为y=kx+b。", encoding="utf-8")
    DocumentService(engine).import_document(course.id, material)
    response = {
        "question_type": "填空题",
        "stem": "一次函数的一般形式是______。",
        "options": [],
        "answer": "y=kx+b",
        "analysis": "依据一次函数定义可得。",
        "scoring_criteria": "正确得5分",
        "knowledge_points": ["一次函数"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }
    result = QuestionGenerationAgent(
        engine, FtsRetriever(engine), MockProvider(response), "mock"
    ).generate(GenerationRequest(course.id, "一次函数", "填空题", 2))
    bank = QuestionBankService(engine)
    assert len(bank.list(course.id, keyword="一般形式", minimum_score=50)) == 1
    bank.update(
        result.question_id,
        QuestionEdit("请写出一次函数的一般形式。", "y=kx+b", "根据定义作答即可。", 6, 2),
    )
    assert len(bank.versions(result.question_id)) == 1
    copy_id = bank.duplicate(result.question_id)
    assert len(bank.list(course.id)) == 2
    bank.delete(copy_id)
    assert len(bank.list(course.id)) == 1
