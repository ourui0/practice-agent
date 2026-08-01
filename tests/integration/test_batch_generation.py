from __future__ import annotations

from types import SimpleNamespace

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
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def test_batch_generation_supplements_scoped_bank(tmp_path) -> None:
    engine = create_database_engine(tmp_path / "batch.db")
    initialize_database(engine)
    course = CourseService(engine).create(CourseInput(name="数学"))
    material = tmp_path / "教材.md"
    material.write_text("# 一次函数\n一次函数的一般形式是 y=kx+b。", encoding="utf-8")
    document = DocumentService(engine).import_document(course.id, material)
    chapter = DocumentService(engine).list_chapters(document.id)[0]
    base_response = {
        "question_type": "填空题",
        "options": [],
        "scoring_criteria": "正确得5分",
        "knowledge_points": ["一次函数"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }
    class VariedProvider:
        def __init__(self) -> None:
            self.calls = 0

        def generate_json(self, _system_prompt, _user_prompt):
            self.calls += 1
            if self.calls == 1:
                return {
                    **base_response,
                    "stem": "一次函数的一般形式是______。",
                    "answer": "y=kx+b",
                    "analysis": "根据一次函数的一般形式作答。",
                }
            return {
                **base_response,
                "stem": "若函数y=(m-2)x+1是一次函数，则m应满足______。",
                "answer": "m不等于2",
                "analysis": "一次函数中自变量系数不能为0，因此m-2不等于0，解得m不等于2。",
            }
    agent = QuestionGenerationAgent(
        engine, FtsRetriever(engine), VariedProvider(), "mock"
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


def test_batch_generation_honors_exact_type_shortages() -> None:
    class RecordingAgent:
        def __init__(self) -> None:
            self.types: list[str] = []

        def generate(self, request):  # type: ignore[no-untyped-def]
            self.types.append(request.question_type)
            return SimpleNamespace(question_id=len(self.types))

    agent = RecordingAgent()
    result = BatchQuestionGenerationService(agent).generate(  # type: ignore[arg-type]
        BatchGenerationRequest(
            course_id=1,
            knowledge_points=("四边形", "平行四边形"),
            question_types=("填空题", "应用题"),
            count=3,
            difficulty=4,
            question_type_counts=(("应用题", 2), ("填空题", 1)),
        )
    )

    assert agent.types == ["填空题", "应用题", "应用题"]
    assert result.created_ids == (1, 2, 3)
    assert result.errors == ()


def test_batch_generation_can_be_cancelled_between_questions() -> None:
    class RecordingAgent:
        def __init__(self) -> None:
            self.count = 0

        def generate(self, request):  # type: ignore[no-untyped-def]
            self.count += 1
            return SimpleNamespace(question_id=self.count)

    agent = RecordingAgent()
    cancel = {"value": False}

    def progress(completed: int, _target: int, _stage: str) -> None:
        if completed == 0:
            cancel["value"] = True

    result = BatchQuestionGenerationService(agent).generate(  # type: ignore[arg-type]
        BatchGenerationRequest(
            course_id=1,
            knowledge_points=("一次函数",),
            question_types=("填空题",),
            count=3,
            difficulty=3,
        ),
        lambda: cancel["value"],
        progress,
    )

    assert result.cancelled
    assert result.created_ids == (1,)
