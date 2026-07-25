from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\出题助手\src")
sys.path.append(r"D:\出题助手\.venv\Lib\site-packages")

from sqlalchemy.orm import Session

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.application.services.paper_service import PaperRequest, PaperService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import QuestionModel


def _question(course_id: int, index: int, question_type: str) -> QuestionModel:
    type_content = {
        "单项选择题": (
            f"下列四边形性质的说法中，正确的是（　　）（样题{index}）",
            '[{"label":"A","content":"对角线相等的四边形是矩形"},'
            '{"label":"B","content":"一组对边平行的四边形是平行四边形"},'
            '{"label":"C","content":"对角线互相垂直的平行四边形是菱形"},'
            '{"label":"D","content":"四个角相等的四边形是正方形"}]',
            "C",
        ),
        "填空题": (
            f"在平行四边形ABCD中，若∠A=68°，则∠B=____°。（样题{index}）",
            "[]",
            "112",
        ),
        "计算题": (
            f"如图意，在菱形ABCD中，对角线AC=12，BD=16，求菱形的周长与面积。（样题{index}）",
            "[]",
            "周长40，面积96",
        ),
        "应用题": (
            f"某矩形绿地长宽之比为3∶2，沿四边铺设步道后总面积增加100平方米。请建立方程解决有关尺寸问题。（样题{index}）",
            "[]",
            "根据题设设未知数并列方程求解",
        ),
    }
    stem, options_json, answer = type_content[question_type]
    return QuestionModel(
        course_id=course_id,
        question_type=question_type,
        stem=stem,
        options_json=options_json,
        answer=answer,
        analysis="依据平行四边形、矩形、菱形与正方形的判定和性质逐步推导。",
        scoring_criteria="过程正确、结论完整得满分。",
        knowledge_points_json='["四边形"]',
        difficulty=4,
        estimated_time_minutes=5,
        score=10,
        quality_score=0.9,
        recommendation_score=90 - index,
        boundary_passed=True,
        status="validated",
        generation_model="acceptance-sample",
    )


database = Path(r"D:\出题助手\tmp\question_type_acceptance.db")
if database.exists():
    database.unlink()
engine = create_database_engine(database)
initialize_database(engine)
course = CourseService(engine).create(CourseInput(name="沪科版八年级数学"))

# 故意乱序写入，验证组题服务会按固定题型顺序重新排列。
source_types = (
    "应用题",
    "填空题",
    "单项选择题",
    "计算题",
    "单项选择题",
    "应用题",
    "填空题",
    "计算题",
    "单项选择题",
    "填空题",
)
with Session(engine) as session, session.begin():
    session.add_all(
        _question(course.id, index, question_type)
        for index, question_type in enumerate(source_types, 1)
    )

quotas = (
    ("单项选择题", 3),
    ("填空题", 3),
    ("计算题", 2),
    ("应用题", 2),
)
service = PaperService(QuestionBankService(engine))
paper = service.assemble(
    PaperRequest(
        course.id,
        "八年级下册四边形·混合题型验收样卷",
        tuple(question_type for question_type, _ in quotas),
        10,
        target_difficulty=4,
        include_answers=True,
        question_type_counts=quotas,
    )
)
assert [question.question_type for question in paper.questions] == [
    "单项选择题",
    "单项选择题",
    "单项选择题",
    "填空题",
    "填空题",
    "填空题",
    "计算题",
    "计算题",
    "应用题",
    "应用题",
]

output = Path(r"D:\出题助手\output\题型数量功能_混合题型验收样卷.docx")
service.export_docx(paper, output)
print(output)
