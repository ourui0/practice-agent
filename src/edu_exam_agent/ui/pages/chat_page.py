"""Teacher-facing multi-turn AI chat page."""

from __future__ import annotations

import html
import json
import re
import threading
import uuid
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.application.services.chat_agent_service import ChatAgentService
from edu_exam_agent.application.services.chat_service import (
    ChatCancelledError,
    ChatResponse,
    ChatService,
    ChatServiceError,
)
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.infrastructure.database.models import (
    ChatMessageModel,
    ChatToolEventModel,
)
from edu_exam_agent.ui.theme import PAGE_MARGINS

_BACKGROUND_CHAT_JOBS: dict[str, tuple[QThread, QObject]] = {}


def markdown_to_safe_html(source: str) -> str:
    """Render a deliberately small Markdown subset after escaping all HTML."""

    lines = source.splitlines()
    output: list[str] = []
    code_lines: list[str] = []
    in_code = False
    list_kind = ""

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = ""

    def inline(value: str) -> str:
        escaped = html.escape(value, quote=True)
        return re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)

    for line in lines:
        if line.strip().startswith("```"):
            close_list()
            if in_code:
                output.append("<pre><code>" + "\n".join(code_lines) + "</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(html.escape(line, quote=True))
            continue
        unordered = re.match(r"^\s*[-*]\s+(.+)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            desired = "ul" if unordered else "ol"
            if list_kind != desired:
                close_list()
                output.append(f"<{desired}>")
                list_kind = desired
            match = unordered or ordered
            output.append(f"<li>{inline(match.group(1))}</li>")
            continue
        close_list()
        if not line.strip():
            output.append("<div class='gap'></div>")
        elif line.startswith("### "):
            output.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            output.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            output.append(f"<h1>{inline(line[2:])}</h1>")
        else:
            output.append(f"<p>{inline(line)}</p>")
    close_list()
    if code_lines:
        output.append("<pre><code>" + "\n".join(code_lines) + "</code></pre>")
    body = "".join(output) or "<p></p>"
    return (
        "<html><head><style>"
        "body{font-family:'Microsoft YaHei','Segoe UI',sans-serif;"
        "font-size:13px;color:#1F1F1F;margin:0;line-height:1.55;}"
        "p{margin:2px 0 7px 0;white-space:pre-wrap;}"
        "h1,h2,h3{margin:8px 0 5px 0;font-weight:600;}"
        "h1{font-size:17px}h2{font-size:15px}h3{font-size:14px}"
        "ul,ol{margin:3px 0 8px 22px;padding:0;}li{margin:2px 0;}"
        "pre{white-space:pre-wrap;word-wrap:break-word;background:#F1F3F4;"
        "border-radius:6px;padding:9px;margin:5px 0 8px 0;}"
        "code{font-family:Consolas,'Microsoft YaHei',monospace;"
        "background:#F1F3F4;padding:1px 3px;border-radius:3px;}"
        "pre code{padding:0}.gap{height:5px}"
        "</style></head><body>"
        + body
        + "</body></html>"
    )


class ChatInputEdit(QPlainTextEdit):
    """Multiline editor where Enter submits and Shift+Enter inserts a line."""

    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ChatMessageBubble(QFrame):
    """A bounded message bubble with safe rich-text rendering."""

    regenerate_requested = Signal()

    def __init__(
        self,
        message: ChatMessageModel,
        allow_regenerate: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        assistant = message.role == "assistant"
        self.setObjectName("AssistantMessageBubble" if assistant else "UserMessageBubble")
        self.setMinimumWidth(420 if assistant else 260)
        self.setMaximumWidth(760)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 10)
        layout.setSpacing(7)

        role = QLabel("AI 助手" if assistant else "教师")
        role.setObjectName("MessageRole")
        layout.addWidget(role)
        self.content_view = QTextBrowser()
        self.content_view.setObjectName("MessageContent")
        self.content_view.setFrameShape(QFrame.Shape.NoFrame)
        self.content_view.setOpenExternalLinks(False)
        self.content_view.setOpenLinks(False)
        self.content_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.content_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.content_view.setHtml(markdown_to_safe_html(message.content))
        self.content_view.document().documentLayout().documentSizeChanged.connect(
            self._fit_content
        )
        layout.addWidget(self.content_view)

        if assistant:
            actions = QHBoxLayout()
            actions.setSpacing(6)
            copy_button = QPushButton("复制")
            copy_button.setObjectName("MessageActionButton")
            copy_button.clicked.connect(
                lambda: QApplication.clipboard().setText(message.content)
            )
            actions.addWidget(copy_button)
            if allow_regenerate:
                regenerate = QPushButton("重新生成")
                regenerate.setObjectName("MessageActionButton")
                regenerate.clicked.connect(self.regenerate_requested)
                actions.addWidget(regenerate)
            actions.addStretch(1)
            layout.addLayout(actions)
        QTimer.singleShot(0, self._fit_content)

    @Slot()
    def _fit_content(self) -> None:
        width = max(220, self.content_view.viewport().width())
        self.content_view.document().setTextWidth(width)
        height = int(self.content_view.document().size().height()) + 6
        self.content_view.setFixedHeight(max(34, min(height, 10_000)))


class ToolExecutionCard(QFrame):
    """Teacher-readable persisted task card; raw tool JSON stays hidden."""

    confirm_requested = Signal(int)
    cancel_requested = Signal(int)
    open_questions_requested = Signal(list)
    open_paper_requested = Signal(int)
    open_export_requested = Signal(str)

    def __init__(
        self, event: ChatToolEventModel, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ToolExecutionCard")
        self.setProperty("kind", event.kind)
        self.setProperty("status", event.status)
        try:
            content = json.loads(event.content_json or "{}")
        except json.JSONDecodeError:
            content = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel(event.title)
        title.setObjectName("ToolCardTitle")
        status = QLabel(self._status_text(event.status))
        status.setObjectName("ToolCardStatus")
        status.setProperty("status", event.status)
        heading.addWidget(title, 1)
        heading.addWidget(status)
        layout.addLayout(heading)
        details = QLabel(self._details(event.kind, content))
        details.setObjectName("ToolCardDetails")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)
        actions = QHBoxLayout()
        actions.setSpacing(7)
        if event.kind == "plan" and event.status == "pending":
            confirm = self._button(
                "重新执行" if content.get("last_error") else "确认执行",
                primary=True,
            )
            confirm.clicked.connect(lambda: self.confirm_requested.emit(event.id))
            cancel = self._button("取消")
            cancel.clicked.connect(lambda: self.cancel_requested.emit(event.id))
            actions.addWidget(confirm)
            actions.addWidget(cancel)
        if event.kind == "generation" and content.get("question_ids"):
            questions = self._button("查看题目")
            questions.clicked.connect(
                lambda: self.open_questions_requested.emit(
                    list(content.get("question_ids", []))
                )
            )
            actions.addWidget(questions)
        if event.kind == "paper" and content.get("paper_id"):
            paper = self._button("预览试卷")
            paper.clicked.connect(
                lambda: self.open_paper_requested.emit(int(content["paper_id"]))
            )
            actions.addWidget(paper)
        if event.kind == "export" and content.get("operation_id"):
            exported = self._button("打开导出文件", primary=True)
            exported.clicked.connect(
                lambda: self.open_export_requested.emit(
                    str(content["operation_id"])
                )
            )
            actions.addWidget(exported)
        actions.addStretch(1)
        if actions.count() > 1:
            layout.addLayout(actions)

    @staticmethod
    def _button(text: str, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ToolCardButton")
        if primary:
            button.setProperty("primary", True)
        return button

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "pending": "等待确认",
            "running": "执行中",
            "completed": "已完成",
            "failed": "未完成",
            "cancelled": "已取消",
        }.get(status, status)

    @staticmethod
    def _details(kind: str, content: dict) -> str:
        if kind == "plan":
            counts = ToolExecutionCard._counts(content.get("question_type_counts", {}))
            lines = [
                f"课程：{content.get('course_name', '')}",
                f"教材：{content.get('document_name', '')}",
                f"章节：{'、'.join(content.get('chapter_names', [])) or '整本教材'}",
                f"难度：第{content.get('difficulty', 3)}档",
                f"题量：{content.get('total_count', 0)}题（{counts}）",
                f"答案与解析：{'包含' if content.get('include_answers') else '不包含'}",
                f"后续操作：{'组卷' if content.get('assemble_paper') else '仅保存题库'}"
                + ("、导出Word" if content.get("export_word") else ""),
            ]
            progress = content.get("progress")
            if isinstance(progress, dict):
                lines.append(
                    f"进度：{progress.get('completed', 0)}/"
                    f"{progress.get('target', content.get('total_count', 0))}　"
                    f"{progress.get('current_stage', '')}"
                )
            if content.get("last_error"):
                lines.append(f"上次未完成：{content['last_error']}")
            return "\n".join(lines)
        if kind == "generation":
            return "\n".join(
                (
                    f"合格题目：{content.get('qualified_count', 0)}/"
                    f"{content.get('target_count', 0)}",
                    f"题型：{ToolExecutionCard._counts(content.get('question_type_counts', {}))}",
                    f"重复淘汰：{content.get('rejected_duplicate_count', 0)}　"
                    f"难度不足：{content.get('rejected_difficulty_count', 0)}　"
                    f"其他质量问题：{content.get('rejected_quality_count', 0)}",
                )
            )
        if kind == "paper":
            if "error" in content:
                return content["error"]
            return (
                f"标题：{content.get('title', '')}\n"
                f"题目数量：{content.get('question_count', 0)}题　"
                f"总分：{content.get('total_score', 0)}分　"
                f"建议时长：{content.get('duration_minutes', 0)}分钟\n"
                f"题型：{ToolExecutionCard._counts(content.get('question_type_counts', {}))}"
            )
        if kind == "export":
            return (
                f"文件：{content.get('filename', '')}\n"
                f"共{content.get('question_count', 0)}题，"
                f"{'包含' if content.get('include_answers') else '不包含'}答案与解析"
            )
        return content.get("message") or content.get("error") or "任务状态已更新。"

    @staticmethod
    def _counts(counts: dict) -> str:
        labels = {
            "单项选择题": "选择题",
            "填空题": "填空题",
            "计算题": "计算题",
            "应用题": "应用题",
        }
        return "、".join(
            f"{labels.get(name, name)}{count}道"
            for name, count in counts.items()
            if count
        ) or "未设置"


class ChatRequestWorker(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, str)
    cancelled = Signal(str, str)
    progress = Signal(str, object)
    finished = Signal()

    def __init__(
        self,
        request_token: str,
        service: ChatService,
        agent_service: ChatAgentService | None,
        conversation_id: int,
        content: str | None,
        action: str,
        cancel_event: threading.Event,
        event_id: int | None = None,
    ) -> None:
        super().__init__()
        self._request_token = request_token
        self._service = service
        self._agent_service = agent_service
        self._conversation_id = conversation_id
        self._content = content
        self._action = action
        self._cancel_event = cancel_event
        self._event_id = event_id

    @Slot()
    def run(self) -> None:
        try:
            if self._action == "regenerate":
                response = self._service.regenerate_last_response(
                    self._conversation_id,
                    self._cancel_event.is_set,
                )
            elif self._action == "confirm":
                if self._agent_service is None or self._event_id is None:
                    raise ChatServiceError("教学智能体尚未初始化")
                response = self._agent_service.confirm_plan(
                    self._conversation_id,
                    self._event_id,
                    self._cancel_event.is_set,
                    self._report_progress,
                )
            elif self._agent_service is not None:
                response = self._agent_service.send_message(
                    self._conversation_id,
                    self._content or "",
                    self._cancel_event.is_set,
                    self._report_progress,
                )
            else:
                response = self._service.send_message(
                    self._conversation_id,
                    self._content or "",
                    self._cancel_event.is_set,
                )
            self.succeeded.emit(self._request_token, response)
        except ChatCancelledError as exc:
            self.cancelled.emit(self._request_token, str(exc))
        except Exception as exc:
            self.failed.emit(self._request_token, str(exc))
        finally:
            self.finished.emit()

    def _report_progress(self, value: dict) -> None:
        self.progress.emit(self._request_token, value)


class ChatPage(QWidget):
    """Modern, persistent chat UI that reuses the configured model."""

    settings_requested = Signal()
    open_question_bank_requested = Signal(list)
    open_paper_requested = Signal(int)
    open_course_requested = Signal(int)
    open_material_requested = Signal(int)

    def __init__(
        self,
        service: ChatService,
        providers: ProviderService,
        agent_service: ChatAgentService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ChatPage")
        self._service = service
        self._providers = providers
        self._agent_service = agent_service
        self._conversation_id: int | None = None
        self._active_token: str | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self._jobs: dict[str, tuple[QThread, ChatRequestWorker]] = {}
        self._switching_history = False
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        page_layout = QVBoxLayout(self)
        left, top, right, bottom = PAGE_MARGINS
        page_layout.setContentsMargins(left, top, right, bottom)
        page_layout.setSpacing(16)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel("AI 对话")
        title.setObjectName("pageTitle")
        subtitle = QLabel("直接使用当前模型，进行连续的教学问答。")
        if self._agent_service is not None:
            subtitle.setText("通过自然语言咨询教学问题，或调用本地工具完成出题与组卷。")
        subtitle.setObjectName("pageSubtitle")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        self.new_button = QPushButton("新建对话")
        self.new_button.clicked.connect(self._new_conversation)
        self.clear_button = QPushButton("清空对话")
        self.clear_button.clicked.connect(self._clear_conversation)
        header.addWidget(self.new_button)
        header.addWidget(self.clear_button)
        page_layout.addLayout(header)

        self.model_card = QFrame()
        self.model_card.setObjectName("ChatStatusCard")
        model_layout = QHBoxLayout(self.model_card)
        model_layout.setContentsMargins(14, 10, 14, 10)
        self.model_label = QLabel()
        self.model_label.setObjectName("ChatModelLabel")
        self.model_state = QLabel()
        self.model_state.setObjectName("ChatConnectionState")
        self.settings_button = QPushButton("前往模型设置")
        self.settings_button.setObjectName("ChatSettingsButton")
        self.settings_button.clicked.connect(self.settings_requested)
        model_layout.addWidget(self.model_label, 1)
        model_layout.addWidget(self.model_state)
        model_layout.addWidget(self.settings_button)
        page_layout.addWidget(self.model_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("ChatSplitter")
        splitter.setChildrenCollapsible(False)

        history_panel = QFrame()
        history_panel.setObjectName("ChatHistoryPanel")
        history_panel.setMinimumWidth(210)
        history_panel.setMaximumWidth(290)
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(12, 14, 12, 12)
        history_layout.setSpacing(8)
        history_header = QHBoxLayout()
        history_title = QLabel("历史对话")
        history_title.setObjectName("ChatPanelTitle")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("ChatDeleteButton")
        self.delete_button.clicked.connect(self._delete_conversation)
        history_header.addWidget(history_title)
        history_header.addStretch(1)
        history_header.addWidget(self.delete_button)
        history_layout.addLayout(history_header)
        self.history_list = QListWidget()
        self.history_list.setObjectName("ChatHistoryList")
        self.history_list.currentItemChanged.connect(self._history_changed)
        history_layout.addWidget(self.history_list, 1)
        splitter.addWidget(history_panel)

        chat_panel = QFrame()
        chat_panel.setObjectName("ChatMainPanel")
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(10)
        self.message_scroll = QScrollArea()
        self.message_scroll.setObjectName("ChatMessageScroll")
        self.message_scroll.setWidgetResizable(True)
        self.message_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.message_container = QWidget()
        self.message_container.setObjectName("ChatMessageContainer")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(16, 16, 16, 16)
        self.message_layout.setSpacing(12)
        self.message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message_scroll.setWidget(self.message_container)
        chat_layout.addWidget(self.message_scroll, 1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.request_status = QLabel("")
        self.request_status.setObjectName("ChatRequestStatus")
        self.request_status.setWordWrap(True)
        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("ChatRetryButton")
        self.retry_button.clicked.connect(self._regenerate_last)
        self.retry_button.hide()
        status_row.addWidget(self.request_status, 1)
        status_row.addWidget(self.retry_button)
        chat_layout.addLayout(status_row)

        input_card = QFrame()
        input_card.setObjectName("ChatInputCard")
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(12, 10, 12, 10)
        input_layout.setSpacing(7)
        editor_row = QHBoxLayout()
        editor_row.setSpacing(10)
        self.input = ChatInputEdit()
        self.input.setObjectName("ChatInput")
        self.input.setPlaceholderText(
            "输入你想咨询的问题，例如：请解释一次函数图象的变化规律……"
        )
        self.input.setMinimumHeight(86)
        self.input.setMaximumHeight(150)
        self.input.submit_requested.connect(self._submit_input)
        self.input.textChanged.connect(self._update_send_state)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("ChatSendButton")
        self.send_button.setProperty("primary", True)
        self.send_button.setFixedWidth(108)
        self.send_button.clicked.connect(self._send_or_stop)
        editor_row.addWidget(self.input, 1)
        editor_row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        input_layout.addLayout(editor_row)
        privacy = QLabel(
            "普通对话不会自动发送教材或题库；执行出题任务时，"
            "只提交当前任务所需的教材片段和查重摘要，不发送 API Key 或本地路径。"
        )
        privacy.setObjectName("ChatPrivacyNotice")
        privacy.setWordWrap(True)
        input_layout.addWidget(privacy)
        chat_layout.addWidget(input_card)
        splitter.addWidget(chat_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([235, 820])
        page_layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        self._refresh_model_state()
        conversations = self._service.list_conversations()
        if self._conversation_id is None:
            if conversations:
                self._conversation_id = conversations[0].id
            else:
                self._conversation_id = self._service.create_conversation().id
        elif not any(item.id == self._conversation_id for item in conversations):
            self._conversation_id = (
                conversations[0].id
                if conversations
                else self._service.create_conversation().id
            )
        self._reload_history()
        self._reload_messages()
        self._update_send_state()

    def reload_courses(self) -> None:
        """Main-window activation hook; chat itself never reads course data."""
        self.refresh()

    def _refresh_model_state(self) -> None:
        config = self._providers.get_default()
        if config is None:
            self.model_label.setText("当前模型：尚未配置")
            self.model_state.setText("不可用")
            self.model_state.setProperty("available", False)
            self.settings_button.show()
            return
        self.model_label.setText(
            f"当前模型：{config.provider_name} / {config.model_name}"
        )
        available = config.has_api_key
        self.model_state.setText("已配置" if available else "缺少 API Key")
        self.model_state.setProperty("available", available)
        self.settings_button.setVisible(not available)
        self.model_state.style().unpolish(self.model_state)
        self.model_state.style().polish(self.model_state)

    def _reload_history(self) -> None:
        conversations = self._service.list_conversations()
        self._switching_history = True
        self.history_list.clear()
        selected_row = -1
        for index, conversation in enumerate(conversations):
            updated = self._format_time(conversation.updated_at)
            item = QListWidgetItem(f"{conversation.title}\n{updated}")
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            item.setToolTip(conversation.title)
            self.history_list.addItem(item)
            if conversation.id == self._conversation_id:
                selected_row = index
        if selected_row >= 0:
            self.history_list.setCurrentRow(selected_row)
        self._switching_history = False
        self.delete_button.setEnabled(self.history_list.count() > 0)

    def _reload_messages(self) -> None:
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._conversation_id is None:
            return
        try:
            messages = self._service.get_messages(self._conversation_id)
            events = (
                self._agent_service.list_events(self._conversation_id)
                if self._agent_service is not None
                else []
            )
        except Exception as exc:
            self.request_status.setText(str(exc))
            return
        if not messages and not events:
            welcome = QLabel(
                "开始一段新对话\n\n可以咨询教学设计、知识点讲解、"
                "解题思路或课堂练习建议。"
            )
            welcome.setObjectName("ChatEmptyState")
            welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
            welcome.setWordWrap(True)
            self.message_layout.addWidget(welcome, 1)
            return
        last_assistant_id = next(
            (message.id for message in reversed(messages) if message.role == "assistant"),
            None,
        )
        events_by_message: dict[int | None, list[ChatToolEventModel]] = {}
        for event in events:
            events_by_message.setdefault(event.message_id, []).append(event)
        for message in messages:
            bubble = ChatMessageBubble(
                message,
                allow_regenerate=(
                    message.id == last_assistant_id
                    and not events_by_message.get(message.id)
                ),
            )
            bubble.regenerate_requested.connect(self._regenerate_last)
            row = QWidget()
            row.setObjectName("ChatMessageRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            if message.role == "user":
                row_layout.addStretch(1)
                row_layout.addWidget(bubble)
            else:
                row_layout.addWidget(bubble)
                row_layout.addStretch(1)
            self.message_layout.addWidget(row)
            for event in events_by_message.get(message.id, []):
                self._append_tool_card(event)
        for event in events_by_message.get(None, []):
            self._append_tool_card(event)
        self.message_layout.addStretch(1)
        QTimer.singleShot(0, self._scroll_to_bottom)

    @Slot()
    def _send_or_stop(self) -> None:
        if self._active_token is not None:
            self._stop_generation()
            return
        self._submit_input()

    @Slot()
    def _submit_input(self) -> None:
        if self._active_token is not None:
            return
        content = self.input.toPlainText().strip()
        if not content or self._conversation_id is None or not self._model_available():
            return
        self.input.clear()
        self._start_request(content=content, regenerate=False)

    @Slot()
    def _regenerate_last(self) -> None:
        if self._active_token is None and self._conversation_id is not None:
            self._start_request(content=None, regenerate=True)

    def _start_request(
        self,
        content: str | None,
        regenerate: bool,
        confirm_event_id: int | None = None,
    ) -> None:
        if self._conversation_id is None:
            return
        token = uuid.uuid4().hex
        cancel_event = threading.Event()
        thread = QThread()
        worker = ChatRequestWorker(
            token,
            self._service,
            self._agent_service,
            self._conversation_id,
            content,
            (
                "confirm"
                if confirm_event_id is not None
                else "regenerate" if regenerate else "send"
            ),
            cancel_event,
            confirm_event_id,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(
            self._request_succeeded,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            self._request_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.cancelled.connect(
            self._request_cancelled,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.progress.connect(
            self._request_progress,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_finished_jobs)
        thread.finished.connect(thread.deleteLater)
        self._jobs[token] = (thread, worker)
        _BACKGROUND_CHAT_JOBS[token] = (thread, worker)
        self._cancel_events[token] = cancel_event
        self._active_token = token
        self._set_busy(True)
        self.retry_button.hide()
        self.request_status.setText(
            "正在执行已确认的出题计划……"
            if confirm_event_id is not None
            else "AI 正在分析要求……"
        )
        if content is not None:
            self._append_temporary_user_message(content)
        thread.start()

    def _append_temporary_user_message(self, content: str) -> None:
        message = ChatMessageModel(
            id=-1,
            conversation_id=self._conversation_id or 0,
            role="user",
            content=content,
            model_name="",
            status="completed",
            created_at=datetime.now(),
        )
        if self.message_layout.count() == 1:
            first = self.message_layout.itemAt(0).widget()
            if first is not None and first.objectName() == "ChatEmptyState":
                self.message_layout.takeAt(0)
                first.deleteLater()
        bubble = ChatMessageBubble(message)
        row = QWidget()
        row.setObjectName("ChatMessageRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addStretch(1)
        row_layout.addWidget(bubble)
        self.message_layout.addWidget(row)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _stop_generation(self) -> None:
        token = self._active_token
        if token is None:
            return
        event = self._cancel_events.get(token)
        if event is not None:
            event.set()
        self._active_token = None
        self._set_busy(False)
        self.retry_button.hide()
        self.request_status.setText("已停止生成；迟到的回复不会写入当前对话。")

    @Slot(str, object)
    def _request_progress(self, token: str, value: dict) -> None:
        if token != self._active_token:
            return
        completed = value.get("completed")
        target = value.get("target")
        stage = value.get("current_stage", "正在执行本地工具")
        prefix = (
            f"{completed}/{target}　"
            if isinstance(completed, int) and isinstance(target, int)
            else ""
        )
        self.request_status.setText(prefix + stage)
        self._reload_messages()

    @Slot(str, object)
    def _request_succeeded(self, token: str, response: ChatResponse) -> None:
        if token != self._active_token:
            return
        self._active_token = None
        self._set_busy(False)
        self.retry_button.hide()
        self.request_status.setText(f"回复完成 · {response.model_name}")
        self._reload_history()
        self._reload_messages()

    @Slot(str, str)
    def _request_failed(self, token: str, message: str) -> None:
        if token != self._active_token:
            return
        self._active_token = None
        self._set_busy(False)
        self.retry_button.show()
        self.request_status.setText(message + " 已输入的问题仍保留，可以重试。")
        self._reload_history()
        self._reload_messages()

    @Slot(str, str)
    def _request_cancelled(self, token: str, message: str) -> None:
        if token != self._active_token:
            return
        self._active_token = None
        self._set_busy(False)
        self.retry_button.hide()
        self.request_status.setText(message)
        self._reload_history()
        self._reload_messages()

    @Slot()
    def _cleanup_finished_jobs(self) -> None:
        finished_tokens = [
            token
            for token, (thread, _worker) in self._jobs.items()
            if thread.isFinished()
        ]
        for token in finished_tokens:
            self._jobs.pop(token, None)
            self._cancel_events.pop(token, None)
            _BACKGROUND_CHAT_JOBS.pop(token, None)

    def _set_busy(self, busy: bool) -> None:
        self.send_button.setText("停止生成" if busy else "发送")
        self.new_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy and self.history_list.count() > 0)
        self.retry_button.setEnabled(not busy)
        self.history_list.setEnabled(not busy)
        self.message_container.setEnabled(not busy)
        self.input.setReadOnly(busy)
        self._update_send_state()

    def _update_send_state(self) -> None:
        if self._active_token is not None:
            self.send_button.setEnabled(True)
            return
        self.send_button.setEnabled(
            bool(self.input.toPlainText().strip()) and self._model_available()
        )

    def _model_available(self) -> bool:
        config = self._providers.get_default()
        return config is not None and config.has_api_key

    def _new_conversation(self) -> None:
        if self._active_token is not None:
            return
        self._conversation_id = self._service.create_conversation().id
        self.request_status.clear()
        self.retry_button.hide()
        self._reload_history()
        self._reload_messages()

    def _clear_conversation(self) -> None:
        if self._conversation_id is None or self._active_token is not None:
            return
        answer = QMessageBox.question(
            self,
            "清空当前对话",
            "确定清空当前对话的全部消息吗？此操作不可撤销。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._service.clear_conversation(self._conversation_id)
        self.request_status.setText("当前对话已清空。")
        self.retry_button.hide()
        self._reload_history()
        self._reload_messages()

    def _delete_conversation(self) -> None:
        item = self.history_list.currentItem()
        if item is None or self._active_token is not None:
            return
        conversation_id = int(item.data(Qt.ItemDataRole.UserRole))
        answer = QMessageBox.question(
            self,
            "删除对话",
            "确定删除这段历史对话吗？此操作不可撤销。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._service.delete_conversation(conversation_id)
        self._conversation_id = None
        self.refresh()

    def _history_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if self._switching_history or current is None or self._active_token is not None:
            return
        self._conversation_id = int(current.data(Qt.ItemDataRole.UserRole))
        self.request_status.clear()
        self.retry_button.hide()
        self._reload_messages()

    def _append_tool_card(self, event: ChatToolEventModel) -> None:
        card = ToolExecutionCard(event)
        card.confirm_requested.connect(self._confirm_plan)
        card.cancel_requested.connect(self._cancel_plan)
        card.open_questions_requested.connect(self.open_question_bank_requested)
        card.open_paper_requested.connect(self.open_paper_requested)
        card.open_export_requested.connect(self._open_export)
        row = QWidget()
        row.setObjectName("ChatToolCardRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(card)
        row_layout.addStretch(1)
        self.message_layout.addWidget(row)

    @Slot(int)
    def _confirm_plan(self, event_id: int) -> None:
        if self._active_token is not None or self._conversation_id is None:
            return
        self._start_request(None, False, confirm_event_id=event_id)

    @Slot(int)
    def _cancel_plan(self, event_id: int) -> None:
        if self._agent_service is None or self._conversation_id is None:
            return
        self._agent_service.cancel_plan(self._conversation_id, event_id)
        self.request_status.setText("出题计划已取消。")
        self._reload_messages()

    @Slot(str)
    def _open_export(self, operation_id: str) -> None:
        if self._agent_service is None:
            return
        path = self._agent_service.resolve_local_path(operation_id)
        if path is None:
            self.request_status.setText("导出文件不存在或已经移动。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _scroll_to_bottom(self) -> None:
        bar = self.message_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancel work and keep QThread wrappers alive until workers return."""
        for cancel_event in self._cancel_events.values():
            cancel_event.set()
        super().closeEvent(event)

    @staticmethod
    def _format_time(value: datetime | None) -> str:
        if value is None:
            return ""
        return value.strftime("%m-%d %H:%M")
