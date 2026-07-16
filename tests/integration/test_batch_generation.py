from __future__ import annotations

from edu_exam_agent.application.services.batch_generation_service import (
    BatchGenerationRequest,
    BatchQuestionGenerationService,
)
from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.question_agent import QuestionGenerationAgent
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def test_batch_generation_supplements_scoped_bank(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "batch.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 一次函数\n一次函数的一般形式是 y=kx+b。", encoding="utf-8")
    document = DocumentService(engine).import_document(course.id, material)
    chapter = DocumentService(engine).list_chapters(document.id)[0]
    response = {
        "question_type": "填空题",
        "stem": "一次函数的一般形式是______。",
        "options": [],
        "answer": "y=kx+b",
        "analysis": "根据一次函数的一般形式作答。",
        "scoring_criteria": "正确得5分",
        "knowledge_points": ["一次函数"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }
    agent = QuestionGenerationAgent(
        engine, FtsRetriever(engine), MockProvider(response), "mock"
    )
    result = BatchQuestionGenerationService(agent).generate(
        BatchGenerationRequest(
            course_id=course.id,
            knowledge_points=("一次函数",),
            question_types=("填空题",),
            count=2,
            difficulty=2,
            document_id=document.id,
            chapter_ids=(chapter.id,),
        )
    )
    assert len(result.created_ids) == 2
    assert result.errors == ()
    assert len(
        QuestionBankService(engine).list(
            course_id=course.id,
            document_id=document.id,
            chapter_ids=(chapter.id,),
        )
    ) == 2

