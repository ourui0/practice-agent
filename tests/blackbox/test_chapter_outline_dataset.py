from __future__ import annotations

import json
from pathlib import Path

import pytest

from edu_exam_agent.application.services.document_processing import recognize_chapters
from edu_exam_agent.infrastructure.parsers import ParsedDocument, ParsedPage


DATASET = Path(__file__).parents[1] / "fixtures" / "chapter_outline_blackbox.json"
CASES = json.loads(DATASET.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_printed_contents_is_the_black_box_authority(case: dict) -> None:
    document = ParsedDocument(
        tuple(
            ParsedPage(page_number, text)
            for page_number, text in enumerate(case["pages"], 1)
        ),
        source_format=".pdf",
    )

    result = recognize_chapters(document)

    assert [chapter.title for chapter in result] == case["expected"]
    assert all(chapter.page_start <= chapter.page_end for chapter in result)
    assert len({chapter.title for chapter in result}) == len(result)
