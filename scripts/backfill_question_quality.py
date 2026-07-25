"""Backfill duplicate fingerprints, mother-model tags and calibrated difficulty."""

from __future__ import annotations

import argparse

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.application.services.question_similarity import (
    QuestionSimilarityService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="扫描历史题库并回填查重与五档难度元数据，不删除或停用题目。"
    )
    parser.add_argument("--course-id", type=int, default=None, help="只处理指定课程")
    args = parser.parse_args()
    context = bootstrap()
    questions, relations = QuestionSimilarityService(context.engine).backfill(args.course_id)
    print(f"已处理 {questions} 道题，记录 {relations} 条相似提示；未删除或停用任何题目。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
