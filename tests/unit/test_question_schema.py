from __future__ import annotations

import pytest
from pydantic import ValidationError

from edu_exam_agent.domain.schemas import GeneratedQuestion


def _payload(options) -> dict:
    return {
        "question_type": "单项选择题",
        "stem": "下列计算结果正确的是（ ）。",
        "options": options,
        "answer": "A",
        "analysis": "根据计算法则逐项判断即可。",
        "scoring_criteria": "选择正确得5分",
        "knowledge_points": ["有理数计算"],
        "difficulty": 2,
        "estimated_time_minutes": 2,
        "score": 5,
    }


def test_string_options_are_normalized_to_structured_options() -> None:
    question = GeneratedQuestion.model_validate(
        _payload(["A. 3", "B、4", "C：5", "D) -3"])
    )
    assert [(item.label, item.content) for item in question.options] == [
        ("A", "3"),
        ("B", "4"),
        ("C", "5"),
        ("D", "-3"),
    ]


def test_unlabelled_string_options_receive_labels() -> None:
    question = GeneratedQuestion.model_validate(_payload(["3", "4", "5", "-3"]))
    assert [item.label for item in question.options] == ["A", "B", "C", "D"]


def test_choice_question_still_requires_four_options() -> None:
    with pytest.raises(ValidationError, match="至少需要四个选项"):
        GeneratedQuestion.model_validate(_payload(["A. 3", "B. 4"]))

