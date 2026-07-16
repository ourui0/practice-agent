"""Repair model-written metadata using persisted textbook source relationships."""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.infrastructure.database.models import (
    DocumentChunkModel,
    KnowledgePointModel,
    QuestionFigureModel,
    QuestionModel,
    QuestionSourceModel,
    QuestionValidationModel,
)

TYPE_ALIASES = {
    "单选题": "单项选择题",
    "单项选择": "单项选择题",
    "选择题": "单项选择题",
    "single_choice": "单项选择题",
    "multiple_choice": "多项选择题",
    "填空": "填空题",
    "fill-in-the-blank": "填空题",
    "calculation": "计算题",
    "application": "应用题",
}
REPAIRABLE_ISSUES = {
    "模型返回题型与要求不一致",
    "知识点标签与要求不一致",
    "题干可能泄露答案",
}
FIGURE_REFERENCE = re.compile(
    r"(?:如|见|根据|观察)(?:下|上)?图(?:所示|中)?|(?:下|上)图(?:所示|中)?|示意图"
)


def main() -> None:
    context = bootstrap()
    repaired = 0
    with Session(context.engine) as session, session.begin():
        questions = list(
            session.scalars(select(QuestionModel).where(QuestionModel.generation_model != ""))
        )
        for question in questions:
            question.question_type = TYPE_ALIASES.get(
                question.question_type.strip(), question.question_type.strip()
            )
            point = session.scalar(
                select(KnowledgePointModel)
                .join(
                    DocumentChunkModel,
                    DocumentChunkModel.chapter_id == KnowledgePointModel.chapter_id,
                )
                .join(
                    QuestionSourceModel,
                    QuestionSourceModel.chunk_id == DocumentChunkModel.id,
                )
                .where(
                    QuestionSourceModel.question_id == question.id,
                    KnowledgePointModel.course_id == question.course_id,
                    KnowledgePointModel.status == "confirmed",
                    KnowledgePointModel.is_enabled.is_(True),
                )
                .order_by(KnowledgePointModel.id)
            )
            if point is not None:
                question.knowledge_points_json = json.dumps([point.name], ensure_ascii=False)
                question.boundary_passed = True
            validation = session.scalar(
                select(QuestionValidationModel)
                .where(QuestionValidationModel.question_id == question.id)
                .order_by(QuestionValidationModel.id.desc())
            )
            if validation is not None:
                issues = [
                    issue
                    for issue in json.loads(validation.issues_json)
                    if issue not in REPAIRABLE_ISSUES
                ]
                visible_text = "\n".join((question.stem, question.analysis))
                has_figure = session.scalar(
                    select(QuestionFigureModel).where(
                        QuestionFigureModel.question_id == question.id
                    )
                )
                if FIGURE_REFERENCE.search(visible_text) and has_figure is None:
                    issues.append("题目引用了未提供的配图")
                quality = max(0.0, round(1.0 - len(issues) * 0.15, 2))
                validation.issues_json = json.dumps(issues, ensure_ascii=False)
                validation.quality_score = quality
                validation.passed = not issues and question.boundary_passed
                question.quality_score = quality
                question.recommendation_score = round(quality * 70 + 30, 2)
                question.status = "validated" if validation.passed else "needs_review"
            repaired += 1
    print(f"已重新校验 {repaired} 道模型生成题目")


if __name__ == "__main__":
    main()
