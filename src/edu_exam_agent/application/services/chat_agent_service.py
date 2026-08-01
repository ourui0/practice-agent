"""Tool-using teaching agent built on the existing chat and generation services."""

from __future__ import annotations

import json
import re
import urllib.error
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.agent_tools.registry import (
    AgentToolRegistry,
    ToolExecutionContext,
)
from edu_exam_agent.application.agent_tools.schemas import PreparedGenerationPlan
from edu_exam_agent.application.services.chat_service import (
    ChatCancelledError,
    ChatResponse,
    ChatService,
    ChatServiceError,
)
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.infrastructure.database.models import (
    ChatConversationModel,
    ChatMessageModel,
    ChatToolEventModel,
)
from edu_exam_agent.infrastructure.llm.provider import ChatMessage, ToolCall

AGENT_SYSTEM_PROMPT = """你是出题助手中的教学任务智能体。

当教师只是咨询知识时，直接回答。
当教师要求查询课程、教材、章节、知识点、题库、生成题目、组卷或导出时，
必须调用提供的程序工具，不能声称已经完成实际未执行的操作。

执行出题前必须依次查询必要的本地信息，并调用 prepare_generation_plan。
prepare_generation_plan 成功后立即停止继续调用工具，等待教师在界面确认计划。
未确认计划时不得调用 generate_single_question、generate_question_batch、
assemble_paper 或 export_paper_word。

不得虚构课程、章节、题目ID、试卷ID或导出文件。
工具失败时必须如实说明；缺少关键参数时应简洁追问。
工具返回的内部ID和原始JSON不要直接展示给教师。
不得请求或泄露 API Key、本地文件路径、整本教材或整个题库。
"""

MAX_TOOL_STEPS = 8
MAX_TOOL_RESULT_CHARACTERS = 12_000
TOOL_INTENT = re.compile(
    r"课程|教材|章节|小节|知识点|题库|出题|生成.{0,30}(?:题|练习|试卷)|"
    r"(?:帮我|请)?出.{0,12}(?:题|练习|试卷)|"
    r"组卷|试卷|导出|"
    r"Word|word|训练题|练习题|多少道题"
)
GENERATION_INTENT = re.compile(
    r"出题|生成.{0,30}(?:题|练习|试卷)|"
    r"(?:帮我|请)?出.{0,12}(?:题|练习|试卷)|"
    r"组卷|导出|训练题|练习题"
)
FOLLOW_UP_INTENT = re.compile(
    r"开始|继续|执行|确认|可以|好的|没问题|按(?:这个|上述|刚才)|"
    r"就这样|生成吧|开始吧"
)


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    conversation_id: int
    message_id: int
    content: str
    model_name: str
    event_ids: tuple[int, ...] = ()


class ChatAgentService:
    """Runs read-only tool loops and confirmed state-changing workflows."""

    def __init__(
        self,
        engine: Engine,
        providers: ProviderService,
        chat: ChatService,
        registry: AgentToolRegistry,
        tool_context: ToolExecutionContext,
        max_history_characters: int = 24_000,
    ) -> None:
        self._engine = engine
        self._providers = providers
        self._chat = chat
        self._registry = registry
        self._tool_context = tool_context
        self._max_history_characters = max(1_000, max_history_characters)
        self._ordinary_context_starts: dict[int, int] = {}

    def send_message(
        self,
        conversation_id: int,
        content: str,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[dict], None] | None = None,
    ) -> ChatResponse | AgentTurnResult:
        clean = content.strip()
        if not clean:
            raise ChatServiceError("请输入要发送的问题")
        explicit_tool_intent = bool(TOOL_INTENT.search(clean))
        continues_workflow = self._continues_tool_workflow(
            conversation_id,
            clean,
        )
        if not explicit_tool_intent and not continues_workflow:
            history_start = self._ordinary_context_starts.get(conversation_id)
            if history_start is not None and not self._message_exists(
                conversation_id,
                history_start,
            ):
                self._ordinary_context_starts.pop(conversation_id, None)
                history_start = None
            reset_history = (
                history_start is None
                and self._has_recent_tool_context(conversation_id)
            )
            response = self._chat.send_message(
                conversation_id,
                clean,
                should_cancel,
                history_start_message_id=history_start,
                reset_history=reset_history,
            )
            if reset_history and response.request_message_id:
                self._ordinary_context_starts[conversation_id] = (
                    response.request_message_id
                )
            return response

        self._ordinary_context_starts.pop(conversation_id, None)
        pending_plan_id = self._pending_plan_id(conversation_id)
        if continues_workflow and pending_plan_id is not None:
            self._save_user(conversation_id, clean)
            message = "出题计划已经准备完成，请点击计划卡片中的“确认执行”。"
            message_id, model_name = self._save_assistant(
                conversation_id,
                message,
                self._current_model_name(),
            )
            return AgentTurnResult(
                conversation_id,
                message_id,
                message,
                model_name,
                (pending_plan_id,),
            )

        requires_plan = bool(GENERATION_INTENT.search(clean)) or (
            continues_workflow
            and self._has_recent_generation_context(conversation_id)
        )
        self._save_user(conversation_id, clean)
        return self._run_tool_turn(
            conversation_id,
            should_cancel or (lambda: False),
            progress or (lambda _value: None),
            requires_plan,
        )

    def _continues_tool_workflow(self, conversation_id: int, content: str) -> bool:
        if len(content) > 40 or not FOLLOW_UP_INTENT.search(content):
            return False
        with Session(self._engine) as session:
            pending_event_id = session.scalar(
                select(ChatToolEventModel.id)
                .where(
                    ChatToolEventModel.conversation_id == conversation_id,
                    ChatToolEventModel.kind == "plan",
                    ChatToolEventModel.status.in_(("pending", "running")),
                )
                .limit(1)
            )
            if pending_event_id is not None:
                return True
            recent_messages = list(
                session.scalars(
                    select(ChatMessageModel.content)
                    .where(ChatMessageModel.conversation_id == conversation_id)
                    .order_by(ChatMessageModel.id.desc())
                    .limit(6)
                )
            )
        return any(TOOL_INTENT.search(message) for message in recent_messages)

    def _has_recent_tool_context(self, conversation_id: int) -> bool:
        with Session(self._engine) as session:
            recent_messages = list(
                session.scalars(
                    select(ChatMessageModel.content)
                    .where(ChatMessageModel.conversation_id == conversation_id)
                    .order_by(ChatMessageModel.id.desc())
                    .limit(12)
                )
            )
            has_tool_event = session.scalar(
                select(ChatToolEventModel.id)
                .where(ChatToolEventModel.conversation_id == conversation_id)
                .limit(1)
            )
        return has_tool_event is not None or any(
            TOOL_INTENT.search(message) for message in recent_messages
        )

    def _message_exists(self, conversation_id: int, message_id: int) -> bool:
        with Session(self._engine) as session:
            return (
                session.scalar(
                    select(ChatMessageModel.id).where(
                        ChatMessageModel.id == message_id,
                        ChatMessageModel.conversation_id == conversation_id,
                    )
                )
                is not None
            )

    def _has_recent_generation_context(self, conversation_id: int) -> bool:
        with Session(self._engine) as session:
            recent_messages = list(
                session.scalars(
                    select(ChatMessageModel.content)
                    .where(ChatMessageModel.conversation_id == conversation_id)
                    .order_by(ChatMessageModel.id.desc())
                    .limit(8)
                )
            )
        return any(
            GENERATION_INTENT.search(message) for message in recent_messages
        )

    def _pending_plan_id(self, conversation_id: int) -> int | None:
        with Session(self._engine) as session:
            return session.scalar(
                select(ChatToolEventModel.id)
                .where(
                    ChatToolEventModel.conversation_id == conversation_id,
                    ChatToolEventModel.kind == "plan",
                    ChatToolEventModel.status == "pending",
                )
                .order_by(ChatToolEventModel.id.desc())
                .limit(1)
            )

    def confirm_plan(
        self,
        conversation_id: int,
        event_id: int,
        should_cancel: Callable[[], bool] | None = None,
        progress: Callable[[dict], None] | None = None,
    ) -> AgentTurnResult:
        cancel = should_cancel or (lambda: False)
        report = progress or (lambda _value: None)
        with Session(self._engine) as session:
            event = session.get(ChatToolEventModel, event_id)
            if (
                event is None
                or event.conversation_id != conversation_id
                or event.kind != "plan"
            ):
                raise ChatServiceError("出题计划不存在或已经失效")
            if event.status == "completed":
                raise ChatServiceError("这份计划已经执行完成，请勿重复提交")
            if event.status == "cancelled":
                raise ChatServiceError("这份计划已经取消")
            raw_plan = json.loads(event.content_json or "{}")
            raw_plan.pop("progress", None)
            raw_plan.pop("last_error", None)
            plan = PreparedGenerationPlan.model_validate(raw_plan)
            run_id = f"chat-plan-{event_id}-{uuid.uuid4().hex[:12]}"
            event.status = "running"
            event.operation_id = run_id
            event.updated_at = datetime.now()
            session.commit()

        context = replace(
            self._tool_context,
            allow_mutations=True,
            should_cancel=cancel,
            progress=lambda value: self._record_progress(event_id, value, report),
        )
        generation_tool = (
            "generate_single_question"
            if (plan.total_count or sum(plan.question_type_counts.values())) == 1
            else "generate_question_batch"
        )
        generated = self._registry.execute(
            ToolCall(
                f"confirm-generate-{event_id}",
                generation_tool,
                {
                    "operation_id": f"{run_id}-generate",
                    "task_id": f"chat-plan-{event_id}-task",
                    "plan": plan.model_dump(mode="json"),
                },
            ),
            context,
        )
        if not generated.succeeded:
            status = generated.content.get("status", "failed")
            if status == "cancelled":
                self._update_event(event_id, status, generated.content)
                raise ChatCancelledError(generated.user_message)
            self._mark_plan_retryable(event_id, generated.user_message)
            raise ChatServiceError(generated.user_message)

        results: list[tuple[str, str, dict, str]] = [
            (
                "generation",
                "单题生成结果" if generation_tool == "generate_single_question" else "题目生成结果",
                generated.content,
                generated.name,
            )
        ]
        paper_result = None
        if plan.assemble_paper and not cancel():
            assembled = self._registry.execute(
                ToolCall(
                    f"confirm-paper-{event_id}",
                    "assemble_paper",
                    {
                        "operation_id": f"{run_id}-paper",
                        "plan": plan.model_dump(mode="json"),
                    },
                ),
                context,
            )
            if assembled.succeeded:
                paper_result = assembled
                results.append(("paper", "试卷生成结果", assembled.content, assembled.name))
            else:
                results.append(
                    (
                        "paper",
                        "试卷尚未组装",
                        {"error": assembled.user_message},
                        assembled.name,
                    )
                )
        if (
            plan.export_word
            and paper_result is not None
            and paper_result.succeeded
            and not cancel()
        ):
            exported = self._registry.execute(
                ToolCall(
                    f"confirm-export-{event_id}",
                    "export_paper_word",
                    {
                        "operation_id": f"{run_id}-export",
                        "paper_id": paper_result.content["paper_id"],
                        "filename": f"{plan.title}.docx",
                    },
                ),
                context,
            )
            if exported.succeeded:
                results.append(("export", "Word 导出结果", exported.content, exported.name))
        if cancel():
            self._update_event(event_id, "cancelled", {"message": "任务已停止"})
            raise ChatCancelledError("任务已停止，未完成的结果不会继续写入")

        summary = self._completion_summary(plan, results)
        message_id, model_name = self._save_assistant(
            conversation_id, summary, self._current_model_name()
        )
        event_ids: list[int] = []
        for kind, title, content_value, tool_name in results:
            event_ids.append(
                self._save_event(
                    conversation_id,
                    message_id,
                    kind,
                    title,
                    "completed" if "error" not in content_value else "failed",
                    tool_name,
                    f"confirmed-{event_id}-{kind}",
                    content_value,
                    content_value.get("operation_id", ""),
                )
            )
        self._update_event(event_id, "completed", plan.model_dump(mode="json"))
        return AgentTurnResult(
            conversation_id,
            message_id,
            summary,
            model_name,
            tuple(event_ids),
        )

    def cancel_plan(self, conversation_id: int, event_id: int) -> None:
        with Session(self._engine) as session:
            event = session.get(ChatToolEventModel, event_id)
            if event is None or event.conversation_id != conversation_id:
                raise ChatServiceError("出题计划不存在")
            if event.status in {"pending", "running"}:
                event.status = "cancelled"
                event.updated_at = datetime.now()
                session.commit()
        self._tool_context.task_controls.cancel(f"chat-plan-{event_id}-task")

    def list_events(self, conversation_id: int) -> list[ChatToolEventModel]:
        with Session(self._engine) as session:
            rows = list(
                session.scalars(
                    select(ChatToolEventModel)
                    .where(
                        ChatToolEventModel.conversation_id == conversation_id,
                        ChatToolEventModel.kind != "audit",
                    )
                    .order_by(ChatToolEventModel.id)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def clear_events(self, conversation_id: int) -> None:
        with Session(self._engine) as session:
            session.execute(
                delete(ChatToolEventModel).where(
                    ChatToolEventModel.conversation_id == conversation_id
                )
            )
            session.commit()

    def resolve_local_path(self, operation_id: str):
        return self._registry.resolve_local_path(operation_id)

    def _run_tool_turn(
        self,
        conversation_id: int,
        cancel: Callable[[], bool],
        progress: Callable[[dict], None],
        requires_plan: bool,
    ) -> AgentTurnResult:
        try:
            provider, model_name = self._providers.create_provider()
        except ValueError as exc:
            raise ChatServiceError(str(exc)) from exc
        messages = self._request_messages(conversation_id)
        seen: set[str] = set()
        pending_plans: list[tuple[ToolCall, dict]] = []
        executed_tool = False
        policy_retries = 0
        context = replace(
            self._tool_context,
            allow_mutations=False,
            should_cancel=cancel,
            progress=progress,
        )
        for step in range(MAX_TOOL_STEPS):
            if cancel():
                raise ChatCancelledError("已停止当前教学任务")
            progress(
                {
                    "status": "running",
                    "completed": step,
                    "target": MAX_TOOL_STEPS,
                    "current_stage": "正在分析要求并查询本地信息",
                }
            )
            try:
                response = provider.chat_with_tools(
                    messages, self._registry.definitions()
                )
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 400:
                    raise ChatServiceError(
                        "当前模型可能不支持工具调用，请在模型设置中选择支持 "
                        "OpenAI function calling 的模型。"
                    ) from exc
                raise ChatService._friendly_error(exc) from exc
            if not response.tool_calls:
                if not executed_tool:
                    if policy_retries < 1:
                        policy_retries += 1
                        messages.append(
                            ChatMessage("assistant", response.content[:1_000])
                        )
                        messages.append(
                            ChatMessage(
                                "system",
                                "当前请求属于程序任务。本轮必须先调用至少一个允许的"
                                "程序工具核对本地信息，不能直接声称已经完成。",
                            )
                        )
                        continue
                    raise ChatServiceError(
                        "当前模型连续未按要求调用程序工具。请重试；"
                        "若仍然出现，请更换支持稳定 function calling 的模型。"
                    )
                if (
                    requires_plan
                    and self._pending_plan_id(conversation_id) is None
                    and not self._is_concise_clarification(response.content)
                ):
                    if policy_retries < 2:
                        policy_retries += 1
                        messages.append(
                            ChatMessage("assistant", response.content[:1_000])
                        )
                        messages.append(
                            ChatMessage(
                                "system",
                                "出题任务尚未调用 prepare_generation_plan。"
                                "不得直接输出题目或声称生成完成；请继续调用工具准备计划，"
                                "信息不足时只能简洁追问。",
                            )
                        )
                        continue
                    raise ChatServiceError(
                        "模型试图绕过出题计划直接输出结果，本次内容已拦截。"
                    )
                content = response.content.strip() or "任务信息不足，请补充具体要求。"
                message_id, _ = self._save_assistant(
                    conversation_id, content, model_name
                )
                return AgentTurnResult(
                    conversation_id, message_id, content, model_name
                )
            messages.append(
                ChatMessage(
                    "assistant",
                    response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                signature = call.name + ":" + json.dumps(
                    call.arguments, ensure_ascii=False, sort_keys=True
                )
                if signature in seen and call.name != "get_generation_progress":
                    result_content = {
                        "error": "相同工具和参数已经执行过，请根据已有结果继续"
                    }
                else:
                    seen.add(signature)
                    result = self._registry.execute(call, context)
                    executed_tool = True
                    result_content = result.content
                    self._save_event(
                        conversation_id,
                        None,
                        "audit",
                        call.name,
                        "completed" if result.succeeded else "failed",
                        call.name,
                        call.id,
                        result.content,
                        str(call.arguments.get("operation_id", "")),
                    )
                    if call.name == "prepare_generation_plan" and result.succeeded:
                        pending_plans.append((call, result.content))
                serialized = json.dumps(result_content, ensure_ascii=False)
                messages.append(
                    ChatMessage(
                        "tool",
                        serialized[:MAX_TOOL_RESULT_CHARACTERS],
                        tool_call_id=call.id,
                    )
                )
            if pending_plans:
                content = (
                    f"已准备 {len(pending_plans)} 份出题计划。"
                    "请核对下方计划卡片，确认后程序才会生成题目、组卷或导出。"
                )
                message_id, _ = self._save_assistant(
                    conversation_id, content, model_name
                )
                event_ids = tuple(
                    self._save_event(
                        conversation_id,
                        message_id,
                        "plan",
                        plan.get("title", "出题计划"),
                        "pending",
                        "prepare_generation_plan",
                        call.id,
                        plan,
                        "",
                    )
                    for call, plan in pending_plans
                )
                return AgentTurnResult(
                    conversation_id, message_id, content, model_name, event_ids
                )
        raise ChatServiceError(
            "本次任务步骤过多，已暂停执行。请缩小出题范围或拆分任务。"
        )

    @staticmethod
    def _is_concise_clarification(content: str) -> bool:
        if not content.strip() or len(content) > 1_200:
            return False
        markers = (
            "？",
            "?",
            "请补充",
            "请确认",
            "请选择",
            "需要",
            "缺少",
            "明确",
            "是否",
        )
        return any(marker in content for marker in markers)

    def _request_messages(self, conversation_id: int) -> list[ChatMessage]:
        with Session(self._engine) as session:
            conversation = session.get(ChatConversationModel, conversation_id)
            if conversation is None:
                raise ChatServiceError("当前对话不存在或已被删除")
            rows = list(
                session.scalars(
                    select(ChatMessageModel)
                    .where(
                        ChatMessageModel.conversation_id == conversation_id,
                        ChatMessageModel.status == "completed",
                    )
                    .order_by(ChatMessageModel.id.desc())
                )
            )
        selected: list[ChatMessageModel] = []
        used = 0
        for row in rows:
            size = len(row.content)
            if selected and used + size > self._max_history_characters:
                break
            selected.append(row)
            used += size
        selected.reverse()
        return [ChatMessage("system", AGENT_SYSTEM_PROMPT)] + [
            ChatMessage(row.role, row.content) for row in selected
        ]

    def _save_user(self, conversation_id: int, content: str) -> int:
        with Session(self._engine) as session:
            conversation = session.get(ChatConversationModel, conversation_id)
            if conversation is None:
                raise ChatServiceError("当前对话不存在或已被删除")
            has_messages = session.scalar(
                select(ChatMessageModel.id)
                .where(ChatMessageModel.conversation_id == conversation_id)
                .limit(1)
            )
            message = ChatMessageModel(
                conversation_id=conversation_id,
                role="user",
                content=content,
                status="completed",
            )
            session.add(message)
            if has_messages is None:
                compact = " ".join(content.split())
                conversation.title = compact[:30] + (
                    "…" if len(compact) > 30 else ""
                )
            conversation.updated_at = datetime.now()
            session.commit()
            return message.id

    def _save_assistant(
        self, conversation_id: int, content: str, model_name: str
    ) -> tuple[int, str]:
        with Session(self._engine) as session:
            conversation = session.get(ChatConversationModel, conversation_id)
            if conversation is None:
                raise ChatServiceError("当前对话已经被删除")
            message = ChatMessageModel(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                model_name=model_name,
                status="completed",
            )
            session.add(message)
            conversation.model_name = model_name
            conversation.updated_at = datetime.now()
            session.commit()
            return message.id, model_name

    def _save_event(
        self,
        conversation_id: int,
        message_id: int | None,
        kind: str,
        title: str,
        status: str,
        tool_name: str,
        tool_call_id: str,
        content: dict,
        operation_id: str,
    ) -> int:
        with Session(self._engine) as session:
            event = ChatToolEventModel(
                conversation_id=conversation_id,
                message_id=message_id,
                kind=kind,
                title=title[:200],
                status=status,
                tool_name=tool_name,
                tool_call_id=tool_call_id[:100],
                operation_id=operation_id[:100],
                content_json=json.dumps(content, ensure_ascii=False),
            )
            session.add(event)
            session.commit()
            return event.id

    def _record_progress(
        self, event_id: int, value: dict, callback: Callable[[dict], None]
    ) -> None:
        with Session(self._engine) as session:
            event = session.get(ChatToolEventModel, event_id)
            if event is not None:
                content = json.loads(event.content_json or "{}")
                content["progress"] = value
                event.status = "running"
                event.content_json = json.dumps(content, ensure_ascii=False)
                event.updated_at = datetime.now()
                session.commit()
        callback({"event_id": event_id, **value})

    def _mark_plan_retryable(self, event_id: int, message: str) -> None:
        with Session(self._engine) as session:
            event = session.get(ChatToolEventModel, event_id)
            if event is not None:
                content = json.loads(event.content_json or "{}")
                content.pop("progress", None)
                content["last_error"] = message
                event.status = "pending"
                event.operation_id = ""
                event.content_json = json.dumps(content, ensure_ascii=False)
                event.updated_at = datetime.now()
                session.commit()

    def _update_event(self, event_id: int, status: str, content: dict) -> None:
        with Session(self._engine) as session:
            event = session.get(ChatToolEventModel, event_id)
            if event is not None:
                event.status = status
                if event.kind != "plan" or status in {"cancelled", "failed"}:
                    event.content_json = json.dumps(content, ensure_ascii=False)
                event.updated_at = datetime.now()
                session.commit()

    def _current_model_name(self) -> str:
        config = self._providers.get_default()
        return config.model_name if config is not None else ""

    @staticmethod
    def _completion_summary(
        plan: PreparedGenerationPlan,
        results: list[tuple[str, str, dict, str]],
    ) -> str:
        generation = next(
            (content for kind, _title, content, _tool in results if kind == "generation"),
            {},
        )
        paper = next(
            (content for kind, _title, content, _tool in results if kind == "paper"),
            {},
        )
        exported = next(
            (content for kind, _title, content, _tool in results if kind == "export"),
            {},
        )
        parts = [
            f"已按“{plan.title}”执行真实出题流程：",
            f"- 合格题目：{generation.get('qualified_count', 0)}/"
            f"{generation.get('target_count', plan.total_count)}",
            f"- 重复淘汰：{generation.get('rejected_duplicate_count', 0)}",
            f"- 难度不足淘汰：{generation.get('rejected_difficulty_count', 0)}",
        ]
        if paper.get("paper_id"):
            parts.append(
                f"- 试卷已组装：{paper.get('question_count', 0)}题，"
                f"总分{paper.get('total_score', 0)}分"
            )
        elif "error" in paper:
            parts.append(f"- 试卷尚未组装：{paper['error']}")
        if exported.get("filename"):
            parts.append(f"- Word 已导出：{exported['filename']}")
        return "\n".join(parts)
