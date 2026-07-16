"""Seed deterministic text-only questions for visual topics that models draw repeatedly."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.infrastructure.database.models import ChapterModel, KnowledgePointModel
from edu_exam_agent.infrastructure.llm import MockProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


def main() -> None:
    context = bootstrap()
    with Session(context.engine) as session:
        point = session.scalar(
            select(KnowledgePointModel).where(KnowledgePointModel.name == "轴对称图形")
        )
        if point is None or point.chapter_id is None:
            raise ValueError("未找到轴对称图形知识点")
        chapter = session.get(ChapterModel, point.chapter_id)
        if chapter is None:
            raise ValueError("未找到知识点对应章节")

    payloads = (
        {
            "question_type": "单项选择题",
            "stem": "在平面直角坐标系中，点P(3，-2)关于y轴的对称点坐标是（ ）。",
            "options": [
                {"label": "A", "content": "(-3，-2)"},
                {"label": "B", "content": "(3，2)"},
                {"label": "C", "content": "(-3，2)"},
                {"label": "D", "content": "(2，-3)"},
            ],
            "answer": "A",
            "analysis": "关于y轴对称时，横坐标互为相反数，纵坐标不变。",
            "scoring_criteria": "选择A得5分。",
            "knowledge_points": ["轴对称图形"],
            "difficulty": 3,
            "estimated_time_minutes": 2,
            "score": 5,
            "diagram": {
                "kind": "coordinate",
                "points": [
                    {"label": "P", "x": 3, "y": -2},
                    {"label": "P'", "x": -3, "y": -2},
                ],
                "segments": [],
                "show_axes": True,
                "caption": "点P关于y轴的对称点",
            },
        },
        {
            "question_type": "填空题",
            "stem": "点A(-4，5)关于x轴的对称点坐标为______。",
            "options": [],
            "answer": "(-4，-5)",
            "analysis": "关于x轴对称时，横坐标不变，纵坐标互为相反数。",
            "scoring_criteria": "坐标填写正确得5分。",
            "knowledge_points": ["轴对称图形"],
            "difficulty": 3,
            "estimated_time_minutes": 2,
            "score": 5,
            "diagram": {
                "kind": "coordinate",
                "points": [
                    {"label": "A", "x": -4, "y": 5},
                    {"label": "A'", "x": -4, "y": -5},
                ],
                "segments": [],
                "show_axes": True,
                "caption": "点A关于x轴的对称点",
            },
        },
    )
    for payload in payloads:
        agent = QuestionGenerationAgent(
            context.engine,
            FtsRetriever(context.engine),
            MockProvider(payload),
            "system-text-fallback",
        )
        agent.generate(
            GenerationRequest(
                course_id=point.course_id,
                knowledge_point=point.name,
                question_type=payload["question_type"],
                difficulty=3,
                document_id=chapter.document_id,
                chapter_ids=(chapter.id,),
            )
        )
    print("已写入 2 道轴对称图形纯文字题")


if __name__ == "__main__":
    main()
