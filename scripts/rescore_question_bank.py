"""Recalculate the entire question bank with the explainable scoring model."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.application.services.question_scoring import (
    QuestionScoreInput,
    calculate_question_score,
    evaluate_question,
)
from edu_exam_agent.domain.schemas import GeneratedQuestion
from edu_exam_agent.infrastructure.database.models import (
    QuestionFigureModel,
    QuestionModel,
    QuestionScoreDetailModel,
    QuestionSourceModel,
    QuestionValidationModel,
)


def main() -> None:
    context = bootstrap()
    scores = []
    with Session(context.engine) as session, session.begin():
        questions = list(session.scalars(select(QuestionModel)))
        for row in questions:
            figure = session.scalar(
                select(QuestionFigureModel).where(QuestionFigureModel.question_id == row.id)
            )
            payload = {
                "question_type": row.question_type,
                "stem": row.stem,
                "options": json.loads(row.options_json),
                "answer": row.answer,
                "analysis": row.analysis,
                "scoring_criteria": row.scoring_criteria,
                "knowledge_points": json.loads(row.knowledge_points_json),
                "difficulty": row.difficulty,
                "estimated_time_minutes": row.estimated_time_minutes,
                "score": row.score,
                "diagram": json.loads(figure.spec_json) if figure else None,
            }
            question = GeneratedQuestion.model_validate(payload)
            validation = session.scalar(
                select(QuestionValidationModel)
                .where(QuestionValidationModel.question_id == row.id)
                .order_by(QuestionValidationModel.id.desc())
            )
            issues = json.loads(validation.issues_json) if validation else []
            evidence_count = session.scalar(
                select(func.count())
                .select_from(QuestionSourceModel)
                .where(QuestionSourceModel.question_id == row.id)
            )
            evaluation = evaluate_question(
                question, evidence_count or 0, row.boundary_passed, issues
            )
            row.quality_score = evaluation.quality_score
            row.recommendation_score = calculate_question_score(
                QuestionScoreInput(evaluation.quality_score, row.difficulty, row.difficulty)
            ).total
            if validation:
                validation.quality_score = evaluation.quality_score
            detail = session.scalar(
                select(QuestionScoreDetailModel).where(
                    QuestionScoreDetailModel.question_id == row.id
                )
            )
            values = {
                "total_points": evaluation.total_points,
                "dimensions_json": json.dumps(evaluation.dimensions, ensure_ascii=False),
                "calculation_load": evaluation.calculation_load,
                "fusion_count": evaluation.fusion_count,
                "reasoning_steps": evaluation.reasoning_steps,
                "hard_point_count": evaluation.hard_point_count,
                "estimated_difficulty": evaluation.estimated_difficulty,
                "notes_json": json.dumps(evaluation.notes, ensure_ascii=False),
            }
            if detail is None:
                session.add(QuestionScoreDetailModel(question_id=row.id, **values))
            else:
                for name, value in values.items():
                    setattr(detail, name, value)
            scores.append(evaluation.total_points)
    print(
        f"已重评分 {len(scores)} 道题；最低 {min(scores):.1f}，"
        f"平均 {sum(scores)/len(scores):.1f}，最高 {max(scores):.1f}"
    )


if __name__ == "__main__":
    main()
