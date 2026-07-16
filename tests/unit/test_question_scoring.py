from __future__ import annotations

import pytest

from edu_exam_agent.application.services.question_scoring import (
    QuestionScoreInput,
    calculate_question_score,
    evaluate_question,
    rank_questions,
)
from edu_exam_agent.domain.schemas import GeneratedQuestion


def test_question_score_combines_quality_and_difficulty_fit() -> None:
    assert calculate_question_score(QuestionScoreInput(0.9, 3, 3)).total == 93


def test_difficulty_mismatch_reduces_score() -> None:
    exact = calculate_question_score(QuestionScoreInput(0.8, 3, 3))
    mismatch = calculate_question_score(QuestionScoreInput(0.8, 1, 3))
    assert exact.total > mismatch.total


def test_rank_questions_filters_and_orders_by_score() -> None:
    ranked = rank_questions(
        [
            ("q-low", QuestionScoreInput(0.5, 1, 3)),
            ("q-high", QuestionScoreInput(0.95, 3, 3)),
            ("q-mid", QuestionScoreInput(0.8, 3, 3)),
        ],
        minimum_score=75,
    )
    assert [question_id for question_id, _ in ranked] == ["q-high", "q-mid"]


def test_invalid_score_is_rejected() -> None:
    with pytest.raises(ValueError):
        calculate_question_score(QuestionScoreInput(1.1, 3, 3))


def test_complex_cross_topic_question_scores_differently_from_simple_recall() -> None:
    simple = GeneratedQuestion.model_validate(
        {
            "question_type": "填空题",
            "stem": "一次函数的一般形式是______。",
            "options": [],
            "answer": "y=kx+b",
            "analysis": "根据定义填写。",
            "scoring_criteria": "正确得5分",
            "knowledge_points": ["一次函数"],
            "difficulty": 1,
            "estimated_time_minutes": 1,
            "score": 5,
        }
    )
    complex_question = GeneratedQuestion.model_validate(
        {
            "question_type": "应用题",
            "stem": "已知一次函数y=2x+1与三角形顶点坐标，分类讨论参数m并求面积最值。",
            "options": [],
            "answer": "m=2时取得最值8",
            "analysis": "首先代入坐标，因为面积关系可得方程；再分类讨论，所以解得m=2。",
            "scoring_criteria": "建模3分，分类讨论4分，结论3分",
            "knowledge_points": ["一次函数", "三角形面积", "分类讨论"],
            "difficulty": 5,
            "estimated_time_minutes": 15,
            "score": 10,
        }
    )
    low = evaluate_question(simple, 1, True)
    high = evaluate_question(complex_question, 3, True)
    assert high.total_points > low.total_points
    assert high.calculation_load > low.calculation_load
    assert high.fusion_count >= 3
    assert high.hard_point_count >= 2
    assert high.estimated_difficulty > low.estimated_difficulty
