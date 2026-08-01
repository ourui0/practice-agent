"""Strict local tool registry used by the teaching chat agent."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.agent_tools.schemas import (
    AssemblePaperArgs,
    CancelTaskArgs,
    CourseArgs,
    EmptyArgs,
    ExportPaperArgs,
    GenerateBatchArgs,
    GenerateSingleArgs,
    GenerationPlanArgs,
    InventoryArgs,
    KnowledgePointArgs,
    PreparedGenerationPlan,
    ProgressArgs,
    TextbookArgs,
    ToolResult,
)
from edu_exam_agent.application.services.batch_generation_service import (
    BatchGenerationRequest,
    BatchQuestionGenerationService,
)
from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import (
    KnowledgePointService,
)
from edu_exam_agent.application.services.paper_service import (
    PaperRequest,
    PaperService,
)
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.question_agent import (
    GenerationRequest,
    QuestionGenerationAgent,
)
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.application.services.question_types import QUESTION_TYPE_ORDER
from edu_exam_agent.infrastructure.database.models import (
    AgentOperationModel,
    CourseModel,
    DocumentModel,
    QuestionDuplicateRelationModel,
    QuestionModel,
)
from edu_exam_agent.infrastructure.llm.provider import ToolCall, ToolDefinition
from edu_exam_agent.infrastructure.retrieval import FtsRetriever


class ToolExecutionError(RuntimeError):
    pass


class ToolCancelledError(ToolExecutionError):
    pass


class TaskControlRegistry:
    """Thread-safe cancellation flags for currently running generation tasks."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}

    def start(self, task_id: str) -> threading.Event:
        with self._lock:
            return self._events.setdefault(task_id, threading.Event())

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            event = self._events.get(task_id)
            if event is None:
                return False
            event.set()
            return True

    def event(self, task_id: str) -> threading.Event | None:
        with self._lock:
            return self._events.get(task_id)

    def finish(self, task_id: str) -> None:
        with self._lock:
            self._events.pop(task_id, None)


@dataclass(slots=True)
class ToolExecutionContext:
    engine: Engine
    courses: CourseService
    documents: DocumentService
    knowledge_points: KnowledgePointService
    bank: QuestionBankService
    papers: PaperService
    providers: ProviderService
    retriever: FtsRetriever
    output_dir: Path
    task_controls: TaskControlRegistry
    allow_mutations: bool = False
    should_cancel: Callable[[], bool] = lambda: False
    progress: Callable[[dict], None] = lambda _value: None


@dataclass(frozen=True, slots=True)
class _ToolSpec:
    definition: ToolDefinition
    arguments_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolExecutionContext], tuple[dict, dict]]
    mutating: bool = False


class AgentToolRegistry:
    """A fixed whitelist; no dynamic imports, code execution, SQL, or file reads."""

    def __init__(self, context: ToolExecutionContext) -> None:
        self._context = context
        self._specs = self._build_specs()

    def definitions(self) -> list[ToolDefinition]:
        return [spec.definition for spec in self._specs.values()]

    def execute(
        self,
        tool_call: ToolCall,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        active = context or self._context
        spec = self._specs.get(tool_call.name)
        if spec is None:
            return ToolResult(
                tool_call.id,
                tool_call.name,
                False,
                {"error": "该工具不在程序允许的白名单中"},
                "无法执行未知工具。",
            )
        try:
            arguments = spec.arguments_model.model_validate(tool_call.arguments)
        except ValidationError as exc:
            message = self._validation_message(exc)
            return ToolResult(
                tool_call.id,
                tool_call.name,
                False,
                {"error": message},
                message,
            )
        if spec.mutating and not active.allow_mutations:
            return ToolResult(
                tool_call.id,
                tool_call.name,
                False,
                {"error": "该操作需要先展示并确认任务计划"},
                "请先确认任务计划，再执行会写入数据的操作。",
            )
        operation_id = str(getattr(arguments, "operation_id", ""))
        if spec.mutating:
            cached = self._cached_operation(operation_id, tool_call)
            if cached is not None:
                return cached
            self._create_operation(operation_id, tool_call)
        try:
            public, private = spec.handler(arguments, active)
        except ToolCancelledError as exc:
            if spec.mutating:
                self._finish_operation(operation_id, "cancelled", {}, {}, str(exc))
            return ToolResult(
                tool_call.id,
                tool_call.name,
                False,
                {"status": "cancelled", "error": str(exc)},
                str(exc),
            )
        except Exception as exc:
            message = str(exc) or "工具执行失败"
            if spec.mutating:
                self._finish_operation(operation_id, "failed", {}, {}, message)
            return ToolResult(
                tool_call.id,
                tool_call.name,
                False,
                {"error": message},
                message,
            )
        if spec.mutating:
            public = dict(public)
            public.setdefault("operation_id", operation_id)
            self._finish_operation(operation_id, "completed", public, private, "")
        return ToolResult(
            tool_call.id,
            tool_call.name,
            True,
            public,
            self._user_message(tool_call.name, public),
            private,
        )

    def resolve_local_path(self, operation_id: str) -> Path | None:
        with Session(self._context.engine) as session:
            row = session.scalar(
                select(AgentOperationModel).where(
                    AgentOperationModel.operation_id == operation_id,
                    AgentOperationModel.status == "completed",
                )
            )
            if row is None:
                return None
            private = json.loads(row.private_json or "{}")
        value = private.get("local_path")
        if not isinstance(value, str):
            return None
        candidate = Path(value).resolve()
        output_root = self._context.output_dir.resolve()
        if candidate != output_root and output_root not in candidate.parents:
            return None
        return candidate if candidate.is_file() else None

    def _build_specs(self) -> dict[str, _ToolSpec]:
        entries = (
            self._spec("list_courses", "查询本地课程列表。", EmptyArgs, self._list_courses),
            self._spec(
                "list_textbooks",
                "查询指定课程已经导入的教材及解析状态。",
                CourseArgs,
                self._list_textbooks,
            ),
            self._spec(
                "list_chapters",
                "查询教材目录中的大章节和小节，名称与目录保持一致。",
                TextbookArgs,
                self._list_chapters,
            ),
            self._spec(
                "list_knowledge_points",
                "查询指定课程和章节中已启用的知识点。",
                KnowledgePointArgs,
                self._list_knowledge_points,
            ),
            self._spec(
                "inspect_question_inventory",
                "检查题库在给定范围、难度和题型配额下的可用数量。",
                InventoryArgs,
                self._inspect_inventory,
            ),
            self._spec(
                "prepare_generation_plan",
                "校验并准备出题计划；该工具不会生成题目或写入题库。",
                GenerationPlanArgs,
                self._prepare_plan,
            ),
            self._spec(
                "generate_question_batch",
                "按已确认计划调用真实教材检索、质量评分和查重流程生成题目。",
                GenerateBatchArgs,
                self._generate_batch,
                True,
            ),
            self._spec(
                "generate_single_question",
                "按已确认的单题计划调用真实教材检索、质量评分和查重流程生成一道题。",
                GenerateSingleArgs,
                self._generate_single,
                True,
            ),
            self._spec(
                "get_generation_progress",
                "查询生成任务当前进度。",
                ProgressArgs,
                self._get_progress,
            ),
            self._spec(
                "cancel_generation_task",
                "停止当前正在运行的生成任务。",
                CancelTaskArgs,
                self._cancel_task,
                True,
            ),
            self._spec(
                "assemble_paper",
                "使用真实题库按选择、填空、计算、应用的固定顺序组装试卷。",
                AssemblePaperArgs,
                self._assemble_paper,
                True,
            ),
            self._spec(
                "export_paper_word",
                "将已经组装的试卷导出为 Word 文档。",
                ExportPaperArgs,
                self._export_word,
                True,
            ),
        )
        return {entry.definition.name: entry for entry in entries}

    @staticmethod
    def _spec(
        name: str,
        description: str,
        model: type[BaseModel],
        handler: Callable[[BaseModel, ToolExecutionContext], tuple[dict, dict]],
        mutating: bool = False,
    ) -> _ToolSpec:
        schema = model.model_json_schema()
        schema["additionalProperties"] = False
        return _ToolSpec(ToolDefinition(name, description, schema), model, handler, mutating)

    @staticmethod
    def _list_courses(
        _args: EmptyArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        items = [
            {
                "course_id": course.id,
                "name": course.name,
                "grade": course.grade,
                "semester": course.semester,
                "textbook_version": course.textbook_version,
                "default_difficulty": course.default_difficulty,
                "default_duration_minutes": course.default_duration_minutes,
            }
            for course in context.courses.list()
        ]
        return {"courses": items[:50], "count": len(items)}, {}

    @staticmethod
    def _list_textbooks(
        args: CourseArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        AgentToolRegistry._require_course(context.engine, args.course_id)
        items = []
        for descriptor in context.documents.list_descriptors(args.course_id):
            document = descriptor.document
            items.append(
                {
                    "document_id": document.id,
                    "name": document.filename,
                    "parse_status": document.parse_status,
                    "chapter_count": document.chapter_count,
                    "health": descriptor.health.state,
                    "ready_for_generation": descriptor.health.ready_for_generation,
                }
            )
        return {"textbooks": items[:30], "count": len(items)}, {}

    @staticmethod
    def _list_chapters(
        args: TextbookArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        document = AgentToolRegistry._require_document(
            context.engine, args.course_id, args.document_id
        )
        outline = context.documents.chapter_outline(args.document_id)
        chapters = [
            {
                "title": item.title,
                "chapter_ids": list(item.chapter_ids),
                "sections": [
                    {"section_id": section.chapter_id, "title": section.title}
                    for section in item.sections
                ],
            }
            for item in outline
        ]
        return {
            "document_id": document.id,
            "document_name": document.filename,
            "chapters": chapters[:40],
        }, {}

    @staticmethod
    def _list_knowledge_points(
        args: KnowledgePointArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        AgentToolRegistry._require_course(context.engine, args.course_id)
        points = [
            {
                "knowledge_point_id": point.id,
                "name": point.name,
                "chapter_id": point.chapter_id,
            }
            for point in context.knowledge_points.list(args.course_id)
            if point.is_enabled
            and point.status == "confirmed"
            and (not args.chapter_ids or point.chapter_id in args.chapter_ids)
        ]
        return {"knowledge_points": points[:100], "count": len(points)}, {}

    @staticmethod
    def _inspect_inventory(
        args: InventoryArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        AgentToolRegistry._require_course(context.engine, args.course_id)
        counts = tuple(args.question_type_counts.items())
        request = PaperRequest(
            course_id=args.course_id,
            title="题库容量检查",
            question_types=tuple(args.question_type_counts),
            count=sum(args.question_type_counts.values()),
            target_difficulty=args.difficulty,
            document_id=args.document_id,
            chapter_ids=tuple(args.chapter_ids),
            question_type_counts=counts,
            exclude_recent_days=180 if args.exclude_recent else 0,
            exclude_recent_papers=20 if args.exclude_recent else 0,
        )
        available = context.papers.available_count_by_type(request)
        requested = args.question_type_counts
        shortages = {
            question_type: max(0, requested.get(question_type, 0) - available.get(question_type, 0))
            for question_type in QUESTION_TYPE_ORDER
            if requested.get(question_type, 0) > 0
        }
        candidates = context.bank.list(
            course_id=args.course_id,
            difficulty=args.difficulty,
            document_id=args.document_id,
            chapter_ids=tuple(args.chapter_ids),
        )
        candidate_ids = [item.id for item in candidates]
        duplicate_count = 0
        if candidate_ids:
            with Session(context.engine) as session:
                duplicate_count = int(
                    session.scalar(
                        select(func.count(QuestionDuplicateRelationModel.id)).where(
                            QuestionDuplicateRelationModel.question_id.in_(candidate_ids),
                            QuestionDuplicateRelationModel.level.in_(("duplicate", "high")),
                        )
                    )
                    or 0
                )
        return {
            "requested_by_type": requested,
            "available_by_type": {
                item: available.get(item, 0) for item in QUESTION_TYPE_ORDER
            },
            "shortages_by_type": shortages,
            "possible_duplicate_count": duplicate_count,
            "needs_ai_backfill": any(shortages.values()),
        }, {}

    @staticmethod
    def _prepare_plan(
        args: GenerationPlanArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        course = AgentToolRegistry._require_course(context.engine, args.course_id)
        document_id = args.document_id
        if document_id is None:
            documents = [
                item
                for item in context.documents.list(args.course_id)
                if item.parse_status == "completed"
            ]
            if len(documents) == 1:
                document_id = documents[0].id
            elif len(documents) > 1:
                raise ValueError("当前课程有多本教材，请先明确选择教材")
            else:
                raise ValueError("当前课程没有解析完成的教材")
        document = AgentToolRegistry._require_document(
            context.engine, args.course_id, document_id
        )
        context.documents.assert_ready_for_generation(document_id)
        outline = context.documents.chapter_outline(document_id)
        chapter_ids = list(args.chapter_ids)
        chapter_names: list[str] = []
        if args.chapter_query and not chapter_ids:
            matches = [
                item
                for item in outline
                if args.chapter_query.strip().lower() in item.title.lower()
                or item.title.lower() in args.chapter_query.strip().lower()
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"“{args.chapter_query}”匹配到{len(matches)}个章节，请明确具体章节"
                )
            chapter_ids = list(matches[0].chapter_ids)
            chapter_names = [matches[0].title]
        valid_ids = {chapter_id for item in outline for chapter_id in item.chapter_ids}
        if chapter_ids and not set(chapter_ids) <= valid_ids:
            raise ValueError("出题计划包含不属于当前教材的章节")
        if not chapter_names:
            chapter_names = [
                item.title for item in outline if set(item.chapter_ids) & set(chapter_ids)
            ]
        points = [
            point
            for point in context.knowledge_points.list(args.course_id)
            if point.status == "confirmed"
            and point.is_enabled
            and (not chapter_ids or point.chapter_id in chapter_ids)
            and (
                not args.knowledge_point_ids or point.id in args.knowledge_point_ids
            )
        ]
        if not points:
            raise ValueError("当前教材范围没有已确认并启用的知识点")
        plan = PreparedGenerationPlan(
            **args.model_dump(exclude={"document_id", "chapter_ids"}),
            document_id=document_id,
            chapter_ids=chapter_ids,
            course_name=course.name,
            document_name=document.filename,
            chapter_names=chapter_names,
            knowledge_points=[point.name for point in points],
        )
        return plan.model_dump(mode="json"), {}

    @staticmethod
    def _generate_batch(
        args: GenerateBatchArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        plan = args.plan
        provider, model_name = context.providers.create_provider()
        agent = QuestionGenerationAgent(
            context.engine, context.retriever, provider, model_name
        )
        task_event = context.task_controls.start(args.task_id)

        def cancelled() -> bool:
            return task_event.is_set() or context.should_cancel()

        def report(completed: int, target: int, stage: str) -> None:
            progress = {
                "task_id": args.task_id,
                "status": "running",
                "completed": completed,
                "target": target,
                "current_stage": stage,
            }
            context.progress(progress)
            AgentToolRegistry._update_progress(
                context.engine, args.operation_id, progress
            )

        request = BatchGenerationRequest(
            course_id=plan.course_id,
            knowledge_points=tuple(plan.knowledge_points),
            question_types=tuple(plan.question_type_counts),
            count=plan.total_count or sum(plan.question_type_counts.values()),
            difficulty=plan.difficulty,
            document_id=plan.document_id,
            chapter_ids=tuple(plan.chapter_ids),
            question_type_counts=tuple(plan.question_type_counts.items()),
        )
        try:
            result = BatchQuestionGenerationService(agent).generate(
                request, cancelled, report
            )
        finally:
            context.task_controls.finish(args.task_id)
        if result.cancelled or cancelled():
            raise ToolCancelledError("出题任务已停止，迟到的结果不会继续写入")
        error_text = "\n".join(result.errors)
        rejected_duplicate = error_text.count("相似") + error_text.count("重复")
        rejected_difficulty = error_text.count("难度") + error_text.count("第五档")
        rejected_quality = max(
            0, len(result.errors) - rejected_duplicate - rejected_difficulty
        )
        counts = AgentToolRegistry._question_counts(context.engine, result.created_ids)
        public = {
            "task_id": args.task_id,
            "status": "completed",
            "target_count": request.count,
            "completed_count": len(result.created_ids),
            "qualified_count": len(result.created_ids),
            "rejected_duplicate_count": rejected_duplicate,
            "rejected_difficulty_count": rejected_difficulty,
            "rejected_quality_count": rejected_quality,
            "question_type_counts": counts,
            "question_ids": list(result.created_ids),
            "quota_satisfied": len(result.created_ids) == request.count,
            "error_summaries": list(result.errors[:3]),
        }
        context.progress(public)
        return public, {}

    @staticmethod
    def _generate_single(
        args: GenerateSingleArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        plan = args.plan
        total_count = plan.total_count or sum(plan.question_type_counts.values())
        if total_count != 1 or len(plan.question_type_counts) != 1:
            raise ValueError("单题生成计划必须且只能包含一道题")
        if not plan.knowledge_points:
            raise ValueError("当前范围没有已确认并启用的知识点")
        question_type, count = next(iter(plan.question_type_counts.items()))
        if count != 1:
            raise ValueError("单题生成计划的题型数量必须为1")

        task_event = context.task_controls.start(args.task_id)

        def cancelled() -> bool:
            return task_event.is_set() or context.should_cancel()

        try:
            if cancelled():
                raise ToolCancelledError("出题任务已停止")
            context.progress(
                {
                    "task_id": args.task_id,
                    "status": "running",
                    "completed": 0,
                    "target": 1,
                    "current_stage": f"正在生成{question_type}",
                }
            )
            provider, model_name = context.providers.create_provider()
            agent = QuestionGenerationAgent(
                context.engine,
                context.retriever,
                provider,
                model_name,
            )
            result = agent.generate(
                GenerationRequest(
                    course_id=plan.course_id,
                    knowledge_point=plan.knowledge_points[0],
                    question_type=question_type,
                    difficulty=plan.difficulty,
                    score=5,
                    strict_material=True,
                    document_id=plan.document_id,
                    chapter_ids=tuple(plan.chapter_ids),
                )
            )
            if cancelled():
                raise ToolCancelledError("出题任务已停止")
        finally:
            context.task_controls.finish(args.task_id)

        public = {
            "task_id": args.task_id,
            "status": "completed",
            "target_count": 1,
            "completed_count": 1,
            "qualified_count": 1,
            "rejected_duplicate_count": 0,
            "rejected_difficulty_count": 0,
            "rejected_quality_count": 0,
            "question_type_counts": {question_type: 1},
            "question_ids": [result.question_id],
            "quota_satisfied": True,
            "error_summaries": [],
        }
        context.progress(
            {
                **public,
                "completed": 1,
                "target": 1,
                "current_stage": "单题生成完成",
            }
        )
        return public, {}

    @staticmethod
    def _get_progress(
        args: ProgressArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        with Session(context.engine) as session:
            rows = list(
                session.scalars(
                    select(AgentOperationModel)
                    .where(AgentOperationModel.request_json.like(f'%"{args.task_id}"%'))
                    .order_by(AgentOperationModel.id.desc())
                    .limit(1)
                )
            )
        if not rows:
            return {
                "task_id": args.task_id,
                "status": "unknown",
                "current_stage": "没有找到该任务",
            }, {}
        row = rows[0]
        result = json.loads(row.result_json or "{}")
        result.update({"task_id": args.task_id, "status": row.status})
        return result, {}

    @staticmethod
    def _cancel_task(
        args: CancelTaskArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        found = context.task_controls.cancel(args.task_id)
        return {
            "task_id": args.task_id,
            "status": "cancelled" if found else "not_running",
        }, {}

    @staticmethod
    def _assemble_paper(
        args: AssemblePaperArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        plan = args.plan
        request = PaperRequest(
            course_id=plan.course_id,
            title=plan.title,
            question_types=tuple(plan.question_type_counts),
            count=plan.total_count or sum(plan.question_type_counts.values()),
            target_difficulty=plan.difficulty,
            include_answers=plan.include_answers,
            duration_minutes=plan.estimated_duration_minutes,
            document_id=plan.document_id,
            chapter_ids=tuple(plan.chapter_ids),
            question_type_counts=tuple(plan.question_type_counts.items()),
            exclude_recent_days=180 if plan.exclude_recent else 0,
            exclude_recent_papers=20 if plan.exclude_recent else 0,
        )
        paper = context.papers.assemble(request)
        counts = AgentToolRegistry._question_counts(
            context.engine, tuple(question.id for question in paper.questions)
        )
        return {
            "paper_id": paper.history_id,
            "title": paper.title,
            "question_count": len(paper.questions),
            "total_score": paper.total_score,
            "duration_minutes": paper.duration_minutes,
            "question_type_counts": counts,
            "question_ids": [question.id for question in paper.questions],
            "include_answers": paper.include_answers,
        }, {}

    @staticmethod
    def _export_word(
        args: ExportPaperArgs, context: ToolExecutionContext
    ) -> tuple[dict, dict]:
        paper = context.papers.load(args.paper_id)
        safe_name = AgentToolRegistry._safe_filename(
            args.filename or f"{paper.title}.docx"
        )
        context.output_dir.mkdir(parents=True, exist_ok=True)
        output = context.papers.export_docx(paper, context.output_dir / safe_name)
        return {
            "paper_id": args.paper_id,
            "succeeded": True,
            "filename": output.name,
            "file_reference": f"word-export:{args.operation_id}",
            "question_count": len(paper.questions),
            "include_answers": paper.include_answers,
        }, {"local_path": str(output.resolve())}

    def _cached_operation(
        self, operation_id: str, tool_call: ToolCall
    ) -> ToolResult | None:
        with Session(self._context.engine) as session:
            row = session.scalar(
                select(AgentOperationModel).where(
                    AgentOperationModel.operation_id == operation_id
                )
            )
            if row is None:
                return None
            content = json.loads(row.result_json or "{}")
            private = json.loads(row.private_json or "{}")
            succeeded = row.status == "completed"
            if not succeeded:
                content = {"status": row.status, "error": row.error_message}
            return ToolResult(
                tool_call.id,
                tool_call.name,
                succeeded,
                content,
                "已返回该操作之前的执行结果，未重复执行。",
                private,
            )

    def _create_operation(self, operation_id: str, tool_call: ToolCall) -> None:
        with Session(self._context.engine) as session:
            session.add(
                AgentOperationModel(
                    operation_id=operation_id,
                    tool_name=tool_call.name,
                    status="running",
                    request_json=json.dumps(tool_call.arguments, ensure_ascii=False),
                )
            )
            session.commit()

    def _finish_operation(
        self,
        operation_id: str,
        status: str,
        result: dict,
        private: dict,
        error: str,
    ) -> None:
        with Session(self._context.engine) as session:
            row = session.scalar(
                select(AgentOperationModel).where(
                    AgentOperationModel.operation_id == operation_id
                )
            )
            if row is not None:
                row.status = status
                row.result_json = json.dumps(result, ensure_ascii=False)
                row.private_json = json.dumps(private, ensure_ascii=False)
                row.error_message = error[:1000]
                row.updated_at = datetime.now()
                session.commit()

    @staticmethod
    def _update_progress(engine: Engine, operation_id: str, value: dict) -> None:
        with Session(engine) as session:
            row = session.scalar(
                select(AgentOperationModel).where(
                    AgentOperationModel.operation_id == operation_id
                )
            )
            if row is not None:
                row.result_json = json.dumps(value, ensure_ascii=False)
                row.updated_at = datetime.now()
                session.commit()

    @staticmethod
    def _require_course(engine: Engine, course_id: int) -> CourseModel:
        with Session(engine) as session:
            course = session.get(CourseModel, course_id)
            if course is None or course.is_archived:
                raise ValueError("课程不存在或已经归档")
            session.expunge(course)
            return course

    @staticmethod
    def _require_document(
        engine: Engine, course_id: int, document_id: int
    ) -> DocumentModel:
        with Session(engine) as session:
            document = session.get(DocumentModel, document_id)
            if document is None or document.course_id != course_id:
                raise ValueError("教材不存在或不属于当前课程")
            session.expunge(document)
            return document

    @staticmethod
    def _question_counts(engine: Engine, question_ids) -> dict[str, int]:
        counts = {question_type: 0 for question_type in QUESTION_TYPE_ORDER}
        if not question_ids:
            return counts
        with Session(engine) as session:
            rows = session.execute(
                select(QuestionModel.question_type, func.count(QuestionModel.id))
                .where(QuestionModel.id.in_(question_ids))
                .group_by(QuestionModel.question_type)
            )
            for question_type, count in rows:
                if question_type in counts:
                    counts[question_type] = int(count)
        return counts

    @staticmethod
    def _safe_filename(value: str) -> str:
        filename = Path(value).name
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
        if not filename:
            filename = "AI生成试卷.docx"
        if not filename.lower().endswith(".docx"):
            filename += ".docx"
        return filename[:180]

    @staticmethod
    def _validation_message(exc: ValidationError) -> str:
        first = exc.errors()[0]
        field = ".".join(str(item) for item in first.get("loc", ())) or "参数"
        return f"工具参数不合法（{field}）：{first.get('msg', '请检查输入')}"

    @staticmethod
    def _user_message(name: str, content: dict) -> str:
        messages = {
            "list_courses": f"找到 {content.get('count', 0)} 门课程。",
            "list_textbooks": f"找到 {content.get('count', 0)} 本教材。",
            "list_chapters": "已读取教材目录。",
            "list_knowledge_points": f"找到 {content.get('count', 0)} 个知识点。",
            "inspect_question_inventory": "已完成题库容量检查。",
            "prepare_generation_plan": "出题计划已准备完成，等待确认。",
            "generate_question_batch": (
                f"已生成 {content.get('qualified_count', 0)} 道合格题目。"
            ),
            "generate_single_question": (
                f"已生成 {content.get('qualified_count', 0)} 道合格题目。"
            ),
            "assemble_paper": (
                f"试卷已组装，共 {content.get('question_count', 0)} 道题。"
            ),
            "export_paper_word": f"Word 已导出：{content.get('filename', '')}",
        }
        return messages.get(name, "工具执行完成。")
