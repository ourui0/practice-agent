"""Batch generation used to supplement an undersized scoped question bank."""

from __future__ import annotations

from dataclasses import dataclass

from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)


@dataclass(frozen=True, slots=True)
class BatchGenerationRequest:
    course_id: int
    knowledge_points: tuple[str, ...]
    question_types: tuple[str, ...]
    count: int
    difficulty: int
    score: int = 5
    document_id: int | None = None
    chapter_ids: tuple[int, ...] = ()

    def validate(self) -> None:
        if not self.knowledge_points:
            raise ValueError("当前范围没有已确认并启用的知识点")
        if not self.question_types:
            raise ValueError("请至少选择一种题型")
        if self.count < 1 or self.count > 100:
            raise ValueError("批量补题数量必须在 1 到 100 之间")
        if self.difficulty not in range(1, 6):
            raise ValueError("难度必须在 1 到 5 之间")


@dataclass(frozen=True, slots=True)
class BatchGenerationResult:
    created_ids: tuple[int, ...]
    errors: tuple[str, ...]


class BatchQuestionGenerationService:
    def __init__(self, agent: QuestionGenerationAgent) -> None:
        self._agent = agent

    def generate(self, request: BatchGenerationRequest) -> BatchGenerationResult:
        request.validate()
        created: list[int] = []
        errors: list[str] = []
        for index in range(request.count):
            point = request.knowledge_points[index % len(request.knowledge_points)]
            question_type = request.question_types[index % len(request.question_types)]
            try:
                result = self._agent.generate(
                    GenerationRequest(
                        course_id=request.course_id,
                        knowledge_point=point,
                        question_type=question_type,
                        difficulty=request.difficulty,
                        score=request.score,
                        strict_material=True,
                        document_id=request.document_id,
                        chapter_ids=request.chapter_ids,
                    )
                )
                created.append(result.question_id)
            except Exception as exc:
                errors.append(f"{point}/{question_type}：{exc}")
        return BatchGenerationResult(tuple(created), tuple(errors))

