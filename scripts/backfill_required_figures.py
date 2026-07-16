"""Generate and persist figures for existing questions that explicitly require them."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.domain.schemas import QuestionDiagram
from edu_exam_agent.infrastructure.database.models import (
    QuestionFigureModel,
    QuestionModel,
    QuestionValidationModel,
)
from edu_exam_agent.infrastructure.llm import OpenAICompatibleProvider
from edu_exam_agent.infrastructure.rendering import render_diagram
from edu_exam_agent.infrastructure.security import SecretStore

FIGURE_REFERENCE = re.compile(
    r"(?:如|见|根据|观察)(?:下|上)?图(?:所示|中)?|(?:下|上)图(?:所示|中)?|示意图"
)
SELF_DRAW = re.compile(r"画出|作出|作图|请画|描点|建立.*坐标系")


def main() -> None:
    context = bootstrap()
    secrets = SecretStore(context.paths.data_dir / "secrets.dat")
    providers = ProviderService(context.engine, secrets)
    config = providers.get_default()
    if config is None:
        raise ValueError("请先配置模型服务")
    key = secrets.get(f"provider:{config.provider_name.lower()}")
    if not key:
        raise ValueError("未找到模型 API Key")
    provider = OpenAICompatibleProvider(config.base_url, "deepseek-v4-flash", key)
    with Session(context.engine) as session:
        questions = list(session.scalars(select(QuestionModel)))
        figured = set(session.scalars(select(QuestionFigureModel.question_id)))
        jobs = [
            question
            for question in questions
            if question.id not in figured
            and FIGURE_REFERENCE.search(f"{question.stem}\n{question.analysis}")
            and not SELF_DRAW.search(question.stem)
        ]
    print(f"必须补图 {len(jobs)} 道", flush=True)

    generated = []
    failed = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_generate, provider, question): question for question in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            question = futures[future]
            try:
                diagram, svg, png = future.result()
                generated.append((question.id, diagram, svg, png))
                print(f"[{index}/{len(jobs)}] 成功：题目 {question.id}", flush=True)
            except Exception as exc:
                failed.append((question.id, str(exc)))
                print(f"[{index}/{len(jobs)}] 失败：题目 {question.id}：{exc}", flush=True)

    with Session(context.engine) as session, session.begin():
        for question_id, diagram, svg, png in generated:
            session.add(
                QuestionFigureModel(
                    question_id=question_id,
                    spec_json=diagram.model_dump_json(),
                    svg_text=svg,
                    png_data=png,
                )
            )
            validation = session.scalar(
                select(QuestionValidationModel)
                .where(QuestionValidationModel.question_id == question_id)
                .order_by(QuestionValidationModel.id.desc())
            )
            question = session.get(QuestionModel, question_id)
            if validation and question:
                issues = [
                    issue
                    for issue in json.loads(validation.issues_json)
                    if issue != "题目引用了未提供的配图"
                ]
                validation.issues_json = json.dumps(issues, ensure_ascii=False)
                validation.passed = not issues and question.boundary_passed
                question.status = "validated" if validation.passed else "needs_review"
    print(f"完成：成功 {len(generated)}，失败 {len(failed)}", flush=True)


def _generate(provider, question: QuestionModel):
    prompt = (
        "你是数学试题制图助手。根据题目生成准确、简洁的结构化示意图，只输出JSON对象。"
        "格式必须是：{kind:'geometry或coordinate',points:[{label,x,y}],"
        "segments:[{start,end,dashed}],show_axes:false,caption:''}。"
        "所有线段端点必须在points中；平行、垂直、全等和平移关系要通过合理位置体现。"
        "不得改变题目条件，不得添加会暗示答案的文字。"
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            payload = provider.generate_json(
                prompt,
                f"题型：{question.question_type}\n题干：{question.stem}\n答案：{question.answer}\n解析：{question.analysis}",
            )
            diagram = QuestionDiagram.model_validate(_normalize_payload(payload))
            svg, png = render_diagram(diagram)
            return diagram, svg, png
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise last_error or RuntimeError("配图生成失败")


def _normalize_payload(payload: object) -> object:
    """Accept common harmless DeepSeek variations without weakening the schema."""
    if not isinstance(payload, dict):
        return payload
    points = payload.get("points")
    segments = payload.get("segments")
    if not isinstance(points, list):
        return payload

    labels: list[str] = []
    used: set[str] = set()
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            labels.append(f"P{index + 1}")
            continue
        label = str(point.get("label") or "").strip() or f"P{index + 1}"
        if label in used:
            label = f"P{index + 1}"
        point["label"] = label
        labels.append(label)
        used.add(label)

    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            for key in ("start", "end"):
                endpoint = segment.get(key)
                if isinstance(endpoint, int) and 0 <= endpoint < len(labels):
                    segment[key] = labels[endpoint]
                elif endpoint is not None:
                    segment[key] = str(endpoint)
    return payload


if __name__ == "__main__":
    main()
