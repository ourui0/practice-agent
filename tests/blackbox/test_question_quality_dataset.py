from __future__ import annotations

import json
from pathlib import Path

from edu_exam_agent.application.services.question_similarity import (
    build_fingerprint,
    compare_fingerprints,
)

DATASET = Path(__file__).parents[1] / "fixtures" / "question_quality_blackbox.json"


def test_question_quality_blackbox_dataset() -> None:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    for case in cases:
        first = build_fingerprint(
            case["first"], case["analysis_first"], ["四边形"], "计算题"
        )
        second = build_fingerprint(
            case["second"], case["analysis_second"], ["四边形"], "计算题"
        )
        result = compare_fingerprints(first, second)
        assert result.level == case["expected_level"], case["name"]
