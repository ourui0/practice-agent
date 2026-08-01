"""Persistent, privacy-bounded multi-turn AI chat use cases."""

from __future__ import annotations

import re
import socket
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.infrastructure.database.models import (
    ChatConversationModel,
    ChatMessageModel,
    ChatToolEventModel,
)
from edu_exam_agent.infrastructure.llm.provider import ChatMessage

SYSTEM_PROMPT = (
    "你是面向初中教师的教学助手。请使用准确、清晰、可直接用于教学的中文回答。\n"
    "涉及数学时必须保证计算和逻辑正确；如果信息不足，应明确指出，不要编造教材内容。\n"
    "始终优先回答教师最新提出的问题，不要延续已经结束或与当前问题无关的旧任务，"
    "也不要用泛化寒暄回避明确问题。"
)


class ChatServiceError(RuntimeError):
    """A teacher-readable chat error."""


class ChatCancelledError(ChatServiceError):
    """The caller no longer wants the pending response."""


@dataclass(frozen=True, slots=True)
class ChatResponse:
    conversation_id: int
    message_id: int
    content: str
    model_name: str
    request_message_id: int = 0


class ChatService:
    """Coordinates model calls while keeping chat data local and recoverable."""

    def __init__(
        self,
        engine: Engine,
        providers: ProviderService,
        max_history_characters: int = 24_000,
    ) -> None:
        self._engine = engine
        self._providers = providers
        self._max_history_characters = max(1_000, max_history_characters)

    def create_conversation(self) -> ChatConversationModel:
        config = self._providers.get_default()
        with Session(self._engine) as session:
            conversation = ChatConversationModel(
                title="新对话",
                model_name=config.model_name if config else "",
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            session.expunge(conversation)
            return conversation

    def list_conversations(self) -> list[ChatConversationModel]:
        with Session(self._engine) as session:
            rows = list(
                session.scalars(
                    select(ChatConversationModel).order_by(
                        ChatConversationModel.updated_at.desc(),
                        ChatConversationModel.id.desc(),
                    )
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def get_messages(self, conversation_id: int) -> list[ChatMessageModel]:
        with Session(self._engine) as session:
            self._require_conversation(session, conversation_id)
            rows = list(
                session.scalars(
                    select(ChatMessageModel)
                    .where(ChatMessageModel.conversation_id == conversation_id)
                    .order_by(ChatMessageModel.id)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def send_message(
        self,
        conversation_id: int,
        content: str,
        should_cancel: Callable[[], bool] | None = None,
        *,
        history_start_message_id: int | None = None,
        reset_history: bool = False,
    ) -> ChatResponse:
        clean_content = content.strip()
        if not clean_content:
            raise ChatServiceError("请输入要发送的问题")
        request_message_id = self._save_user_message(conversation_id, clean_content)
        return self._generate_reply(
            conversation_id,
            should_cancel,
            history_start_message_id=(
                request_message_id if reset_history else history_start_message_id
            ),
            request_message_id=request_message_id,
        )

    def regenerate_last_response(
        self,
        conversation_id: int,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ChatResponse:
        replace_message_id: int | None = None
        with Session(self._engine) as session:
            self._require_conversation(session, conversation_id)
            last_message = session.scalar(
                select(ChatMessageModel)
                .where(ChatMessageModel.conversation_id == conversation_id)
                .order_by(ChatMessageModel.id.desc())
                .limit(1)
            )
            if last_message is None:
                raise ChatServiceError("当前对话还没有可重新生成的消息")
            if last_message.role == "assistant":
                replace_message_id = last_message.id
            elif last_message.role != "user":
                raise ChatServiceError("当前对话还没有可重新生成的教师问题")
        return self._generate_reply(
            conversation_id,
            should_cancel,
            replace_message_id=replace_message_id,
        )

    def clear_conversation(self, conversation_id: int) -> None:
        with Session(self._engine) as session:
            conversation = self._require_conversation(session, conversation_id)
            session.execute(
                delete(ChatMessageModel).where(
                    ChatMessageModel.conversation_id == conversation_id
                )
            )
            session.execute(
                delete(ChatToolEventModel).where(
                    ChatToolEventModel.conversation_id == conversation_id
                )
            )
            conversation.title = "新对话"
            conversation.updated_at = datetime.now()
            session.commit()

    def delete_conversation(self, conversation_id: int) -> None:
        with Session(self._engine) as session:
            conversation = session.get(ChatConversationModel, conversation_id)
            if conversation is not None:
                session.delete(conversation)
                session.commit()

    def _save_user_message(self, conversation_id: int, content: str) -> int:
        with Session(self._engine) as session:
            conversation = self._require_conversation(session, conversation_id)
            existing_count = session.scalar(
                select(func.count(ChatMessageModel.id)).where(
                    ChatMessageModel.conversation_id == conversation_id
                )
            )
            message = ChatMessageModel(
                conversation_id=conversation_id,
                role="user",
                content=content,
                status="completed",
            )
            session.add(message)
            if not existing_count:
                conversation.title = self._make_title(content)
            conversation.updated_at = datetime.now()
            session.commit()
            return message.id

    def _generate_reply(
        self,
        conversation_id: int,
        should_cancel: Callable[[], bool] | None,
        replace_message_id: int | None = None,
        history_start_message_id: int | None = None,
        request_message_id: int = 0,
    ) -> ChatResponse:
        cancel = should_cancel or (lambda: False)
        provider, model_name = self._create_provider()
        messages = self._request_messages(
            conversation_id,
            replace_message_id,
            history_start_message_id,
        )
        if cancel():
            raise ChatCancelledError("已停止生成，教师问题已保留")
        try:
            content = provider.chat(messages).strip()
            latest_user = next(
                (message.content for message in reversed(messages) if message.role == "user"),
                "",
            )
            if self._looks_like_generic_deflection(latest_user, content):
                content = provider.chat(
                    [
                        ChatMessage("system", SYSTEM_PROMPT),
                        ChatMessage(
                            "system",
                            "上一条回复没有回答教师的问题。请直接回答，不要寒暄或反问需求。",
                        ),
                        ChatMessage("user", latest_user),
                    ]
                ).strip()
        except Exception as exc:
            raise self._friendly_error(exc) from exc
        if cancel():
            raise ChatCancelledError("已停止生成，迟到的回复不会保存")
        if not content:
            raise ChatServiceError("模型没有返回有效内容，可以稍后重试")

        with Session(self._engine) as session:
            conversation = session.get(ChatConversationModel, conversation_id)
            if conversation is None:
                raise ChatServiceError("当前对话已被删除，回复未保存")
            if cancel():
                raise ChatCancelledError("已停止生成，迟到的回复不会保存")
            if replace_message_id is not None:
                previous = session.get(ChatMessageModel, replace_message_id)
                if (
                    previous is not None
                    and previous.conversation_id == conversation_id
                    and previous.role == "assistant"
                ):
                    session.delete(previous)
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
            session.refresh(message)
            return ChatResponse(
                conversation_id,
                message.id,
                content,
                model_name,
                request_message_id,
            )

    def _request_messages(
        self,
        conversation_id: int,
        excluded_message_id: int | None = None,
        history_start_message_id: int | None = None,
    ) -> list[ChatMessage]:
        with Session(self._engine) as session:
            self._require_conversation(session, conversation_id)
            conditions = [
                ChatMessageModel.conversation_id == conversation_id,
                ChatMessageModel.status == "completed",
            ]
            if excluded_message_id is not None:
                conditions.append(ChatMessageModel.id != excluded_message_id)
            if history_start_message_id is not None:
                conditions.append(ChatMessageModel.id >= history_start_message_id)
            rows = list(
                session.scalars(
                    select(ChatMessageModel)
                    .where(*conditions)
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
        return [ChatMessage("system", SYSTEM_PROMPT)] + [
            ChatMessage(row.role, row.content) for row in selected
        ]

    @staticmethod
    def _looks_like_generic_deflection(question: str, response: str) -> bool:
        if not question or re.fullmatch(
            r"(?:你好|您好|嗨|hi|hello|在吗)[！!。.\s]*",
            question,
            flags=re.IGNORECASE,
        ):
            return False
        markers = (
            "有什么想聊",
            "需要我帮",
            "有什么可以帮",
            "尽管说",
            "随时可以",
            "请告诉我你想",
        )
        return sum(marker in response for marker in markers) >= 2

    def _create_provider(self):
        try:
            return self._providers.create_provider()
        except ValueError as exc:
            raise ChatServiceError(str(exc)) from exc

    @staticmethod
    def _require_conversation(
        session: Session, conversation_id: int
    ) -> ChatConversationModel:
        conversation = session.get(ChatConversationModel, conversation_id)
        if conversation is None:
            raise ChatServiceError("当前对话不存在或已被删除")
        return conversation

    @staticmethod
    def _make_title(content: str) -> str:
        compact = " ".join(content.split())
        return compact[:30] + ("…" if len(compact) > 30 else "")

    @staticmethod
    def _friendly_error(exc: Exception) -> ChatServiceError:
        if isinstance(exc, urllib.error.HTTPError):
            if exc.code in (401, 403):
                return ChatServiceError("模型服务拒绝了请求，请检查 API Key 和访问权限")
            if exc.code == 429:
                return ChatServiceError("模型服务当前请求较多，请稍后重试")
            if exc.code == 404:
                return ChatServiceError("没有找到当前模型，请检查模型名称")
            return ChatServiceError(f"模型服务暂时不可用（状态码 {exc.code}）")
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return ChatServiceError(
                "模型响应超时，本次消息没有生成完成。你可以稍后重试，"
                "已输入的问题不会丢失。"
            )
        if isinstance(exc, urllib.error.URLError):
            return ChatServiceError("无法连接模型服务，请检查网络后重试")
        if isinstance(exc, ValueError):
            return ChatServiceError(str(exc))
        return ChatServiceError("模型回复失败，请稍后重试")
