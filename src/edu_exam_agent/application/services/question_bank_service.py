"""Question bank filtering, editing and version history."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.models import (
    DocumentChunkModel,
    QuestionFigureModel,
    QuestionModel,
    QuestionScoreDetailModel,
    QuestionSourceModel,
    QuestionVersionModel,
)


@dataclass(frozen=True, slots=True)
class QuestionEdit:
    stem: str
    answer: str
    analysis: str
    score: int
    difficulty: int

    def validate(self) -> None:
        if len(self.stem.strip()) < 5 or not self.answer.strip() or len(self.analysis.strip()) < 5:
            raise ValueError("题干、答案和解析不能为空")
        if self.score < 1 or self.difficulty not in range(1, 6):
            raise ValueError("分值或难度不合法")


class QuestionBankService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(
        self,
        course_id: int | None = None,
        keyword: str = "",
        question_type: str = "",
        difficulty: int | None = None,
        minimum_score: float = 0,
        document_id: int | None = None,
        chapter_ids: tuple[int, ...] = (),
    ) -> list[QuestionModel]:
        statement = select(QuestionModel)
        if course_id is not None:
            statement = statement.where(QuestionModel.course_id == course_id)
        if keyword.strip():
            pattern = f"%{keyword.strip()}%"
            statement = statement.where(
                or_(QuestionModel.stem.like(pattern), QuestionModel.analysis.like(pattern))
            )
        if question_type:
            statement = statement.where(QuestionModel.question_type == question_type)
        if difficulty is not None:
            statement = statement.where(QuestionModel.difficulty == difficulty)
        statement = statement.where(QuestionModel.recommendation_score >= minimum_score)
        if document_id is not None or chapter_ids:
            source = (
                select(QuestionSourceModel.id)
                .join(DocumentChunkModel, DocumentChunkModel.id == QuestionSourceModel.chunk_id)
                .where(QuestionSourceModel.question_id == QuestionModel.id)
            )
            if document_id is not None:
                source = source.where(DocumentChunkModel.document_id == document_id)
            if chapter_ids:
                source = source.where(DocumentChunkModel.chapter_id.in_(chapter_ids))
            statement = statement.where(source.exists())
        statement = statement.order_by(
            QuestionModel.recommendation_score.desc(), QuestionModel.id.desc()
        )
        with Session(self._engine) as session:
            return list(session.scalars(statement))

    def update(self, question_id: int, value: QuestionEdit) -> None:
        value.validate()
        with Session(self._engine) as session, session.begin():
            question = session.get(QuestionModel, question_id)
            if question is None:
                raise ValueError("题目不存在")
            before = self._snapshot(question)
            changed = [
                name
                for name in ("stem", "answer", "analysis", "score", "difficulty")
                if getattr(question, name) != getattr(value, name)
            ]
            session.add(
                QuestionVersionModel(
                    question_id=question.id,
                    snapshot_json=json.dumps(before, ensure_ascii=False),
                    changed_fields=json.dumps(changed, ensure_ascii=False),
                    changed_by="teacher",
                )
            )
            question.stem = value.stem.strip()
            question.answer = value.answer.strip()
            question.analysis = value.analysis.strip()
            question.score = value.score
            question.difficulty = value.difficulty
            question.status = "teacher_edited"

    def duplicate(self, question_id: int) -> int:
        with Session(self._engine) as session, session.begin():
            source = session.get(QuestionModel, question_id)
            if source is None:
                raise ValueError("题目不存在")
            data = self._snapshot(source)
            data.pop("id", None)
            data["stem"] = f"{data['stem']}（副本）"
            data["status"] = "draft"
            copy = QuestionModel(**data)
            session.add(copy)
            session.flush()
            return copy.id

    def delete(self, question_id: int) -> None:
        with Session(self._engine) as session:
            question = session.get(QuestionModel, question_id)
            if question:
                session.delete(question)
                session.commit()

    def versions(self, question_id: int) -> list[QuestionVersionModel]:
        with Session(self._engine) as session:
            statement = (
                select(QuestionVersionModel)
                .where(QuestionVersionModel.question_id == question_id)
                .order_by(QuestionVersionModel.id.desc())
            )
            return list(session.scalars(statement))

    def figure(self, question_id: int) -> QuestionFigureModel | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(QuestionFigureModel).where(QuestionFigureModel.question_id == question_id)
            )

    def score_detail(self, question_id: int) -> QuestionScoreDetailModel | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(QuestionScoreDetailModel).where(
                    QuestionScoreDetailModel.question_id == question_id
                )
            )

    @staticmethod
    def _snapshot(question: QuestionModel) -> dict:
        return {
            "id": question.id,
            "course_id": question.course_id,
            "question_type": question.question_type,
            "stem": question.stem,
            "options_json": question.options_json,
            "answer": question.answer,
            "analysis": question.analysis,
            "scoring_criteria": question.scoring_criteria,
            "knowledge_points_json": question.knowledge_points_json,
            "difficulty": question.difficulty,
            "estimated_time_minutes": question.estimated_time_minutes,
            "score": question.score,
            "quality_score": question.quality_score,
            "recommendation_score": question.recommendation_score,
            "boundary_passed": question.boundary_passed,
            "status": question.status,
            "generation_model": question.generation_model,
        }
