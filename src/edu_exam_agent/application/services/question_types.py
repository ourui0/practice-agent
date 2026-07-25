"""Canonical question-type order shared by generation, assembly and export."""

from __future__ import annotations

QUESTION_TYPE_ORDER = (
    "单项选择题",
    "填空题",
    "计算题",
    "应用题",
)

QUESTION_TYPE_LABELS = {
    "单项选择题": "选择题",
    "填空题": "填空题",
    "计算题": "计算题",
    "应用题": "应用题",
}


def ordered_type_counts(
    values: tuple[tuple[str, int], ...],
) -> tuple[tuple[str, int], ...]:
    """Return positive quotas in the canonical display order."""
    counts = dict(values)
    return tuple(
        (question_type, counts[question_type])
        for question_type in QUESTION_TYPE_ORDER
        if counts.get(question_type, 0) > 0
    )
