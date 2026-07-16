"""Prefill the real question bank from confirmed textbook knowledge points."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.application.services.knowledge_point_service import KnowledgePointService
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.infrastructure.database.models import ChapterModel, QuestionModel
from edu_exam_agent.infrastructure.llm import OpenAICompatibleProvider
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.infrastructure.security import SecretStore

DEFAULT_TYPES = ("单项选择题", "填空题", "计算题", "应用题")


def main() -> int:
    parser = argparse.ArgumentParser(description="按教材知识点预生成题库")
    parser.add_argument("--per-combination", type=int, default=1)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    if args.per_combination not in range(1, 6):
        parser.error("--per-combination 必须在 1 到 5 之间")

    context = bootstrap()
    points_service = KnowledgePointService(context.engine)
    secrets = SecretStore(context.paths.data_dir / "secrets.dat")
    providers = ProviderService(context.engine, secrets)
    provider, model = providers.create_provider()
    if args.model:
        config = providers.get_default()
        if config is None:
            raise ValueError("请先配置模型服务")
        key = secrets.get(f"provider:{config.provider_name.lower()}")
        if not key:
            raise ValueError("未找到模型 API Key")
        model = args.model
        provider = OpenAICompatibleProvider(config.base_url, model, key)
    agent = QuestionGenerationAgent(
        context.engine, FtsRetriever(context.engine), provider, model
    )

    with Session(context.engine) as session:
        chapters = {row.id: row for row in session.scalars(select(ChapterModel))}
        existing = Counter()
        for question in session.scalars(select(QuestionModel)):
            if question.status not in {"validated", "teacher_edited"}:
                continue
            try:
                names = json.loads(question.knowledge_points_json)
            except json.JSONDecodeError:
                names = []
            for name in names:
                existing[(question.course_id, name, question.question_type)] += 1

    jobs = []
    for course_id in {point.course_id for point in _all_points(points_service, context.engine)}:
        for point in points_service.list(course_id):
            if point.status != "confirmed" or not point.is_enabled:
                continue
            chapter = chapters.get(point.chapter_id)
            for question_type in DEFAULT_TYPES:
                missing = args.per_combination - existing[
                    (course_id, point.name, question_type)
                ]
                for _ in range(max(missing, 0)):
                    jobs.append((point, chapter, question_type))

    print(f"待生成 {len(jobs)} 道题，模型：{model}", flush=True)
    succeeded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=min(max(args.workers, 1), 6)) as executor:
        futures = {
            executor.submit(_generate_one, agent, job, args.delay): job for job in jobs
        }
        for index, future in enumerate(as_completed(futures), 1):
            point, _chapter, question_type = futures[future]
            error = future.result()
            if error is None:
                succeeded += 1
                print(
                    f"[{index}/{len(jobs)}] 成功：{point.name} / {question_type}",
                    flush=True,
                )
            else:
                failed += 1
                print(
                    f"[{index}/{len(jobs)}] 失败：{point.name} / {question_type}：{error}",
                    flush=True,
                )
    print(f"完成：成功 {succeeded}，失败 {failed}", flush=True)
    return 0 if failed == 0 else 2


def _all_points(service: KnowledgePointService, engine) -> list:
    with Session(engine) as session:
        course_ids = {
            course_id
            for (course_id,) in session.execute(
                select(QuestionModel.course_id).distinct()
            )
        }
        from edu_exam_agent.infrastructure.database.models import CourseModel

        course_ids.update(session.scalars(select(CourseModel.id)))
    return [point for course_id in course_ids for point in service.list(course_id)]


def _generate_one(agent, job, delay: float) -> str | None:
    point, chapter, question_type = job
    for attempt in range(1, 3):
        try:
            agent.generate(
                GenerationRequest(
                    course_id=point.course_id,
                    knowledge_point=point.name,
                    question_type=question_type,
                    difficulty=point.recommended_difficulty,
                    score=5,
                    strict_material=True,
                    document_id=chapter.document_id if chapter else None,
                    chapter_ids=(chapter.id,) if chapter else (),
                )
            )
            if delay:
                time.sleep(delay)
            return None
        except Exception as exc:
            if attempt == 2:
                return str(exc)
            time.sleep(1.5)
    return "未知错误"


if __name__ == "__main__":
    raise SystemExit(main())
