from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt, QThread
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from edu_exam_agent.application.services.chat_service import ChatResponse, ChatService
from edu_exam_agent.application.services.provider_service import (
    ProviderConfig,
    ProviderService,
)
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)
from edu_exam_agent.infrastructure.database.models import ChatMessageModel
from edu_exam_agent.infrastructure.security import SecretStore
from edu_exam_agent.ui.pages.chat_page import (
    ChatInputEdit,
    ChatMessageBubble,
    ChatPage,
    ToolExecutionCard,
    markdown_to_safe_html,
)
from edu_exam_agent.ui.windows.main_window import MainWindow


def test_chat_page_disables_send_without_model_and_shows_privacy_notice(
    tmp_path,
) -> None:
    application = QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "chat-ui.db")
    initialize_database(engine)
    providers = ProviderService(engine, SecretStore(tmp_path / "secrets.dat"))
    page = ChatPage(ChatService(engine, providers), providers)
    page.input.setPlainText("测试问题")
    application.processEvents()

    assert page.objectName() == "ChatPage"
    assert not page.send_button.isEnabled()
    assert "尚未配置" in page.model_label.text()
    notices = [label.text() for label in page.findChildren(type(page.model_label))]
    assert any("不会自动发送教材" in text for text in notices)
    page.close()


def test_chat_input_enter_submits_and_shift_enter_adds_newline() -> None:
    _application = QApplication.instance() or QApplication([])
    editor = ChatInputEdit()
    spy = QSignalSpy(editor.submit_requested)
    editor.show()
    editor.setFocus()

    QTest.keyClicks(editor, "line")
    QTest.keyClick(
        editor,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ShiftModifier,
    )
    QTest.keyClicks(editor, "two")
    assert editor.toPlainText() == "line\ntwo"
    assert spy.count() == 0

    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert spy.count() == 1
    assert editor.toPlainText() == "line\ntwo"
    editor.close()


def test_markdown_renderer_escapes_html_and_keeps_math_text() -> None:
    rendered = markdown_to_safe_html(
        "<script>alert(1)</script>\n- 列表\n```python\nx = 1\n```\n\\frac{1}{2}"
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<ul>" in rendered
    assert "<pre><code>" in rendered
    assert "\\frac{1}{2}" in rendered


def test_assistant_copy_button_copies_complete_reply() -> None:
    application = QApplication.instance() or QApplication([])
    message = ChatMessageModel(
        id=1,
        conversation_id=1,
        role="assistant",
        content="第一行\n第二行与公式 x²+y²=z²",
        model_name="test-model",
        status="completed",
    )
    bubble = ChatMessageBubble(message, allow_regenerate=True)
    buttons = bubble.findChildren(QPushButton)
    QTest.mouseClick(
        next(button for button in buttons if button.text() == "复制"),
        Qt.MouseButton.LeftButton,
    )
    assert application.clipboard().text() == message.content
    assert any(button.text() == "重新生成" for button in buttons)
    bubble.close()


def test_chat_page_renders_without_clipping_at_common_scales(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "chat-scale.db")
    initialize_database(engine)
    providers = ProviderService(engine, SecretStore(tmp_path / "scale-secrets.dat"))
    page = ChatPage(ChatService(engine, providers), providers)
    page.resize(1040, 680)
    page.show()
    application.processEvents()

    for scale in (1.0, 1.25, 1.5):
        image = QImage(
            round(page.width() * scale),
            round(page.height() * scale),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(QColor("#F8F9FA"))
        painter = QPainter(image)
        painter.scale(scale, scale)
        page.render(painter, QPoint())
        painter.end()
        assert not image.isNull()
        assert page.rect().contains(
            page.send_button.mapTo(page, page.send_button.rect().center())
        )
        assert page.rect().contains(page.input.mapTo(page, page.input.rect().center()))
    page.close()


def test_tool_plan_card_shows_safe_summary_and_confirmation_actions() -> None:
    application = QApplication.instance() or QApplication([])
    from edu_exam_agent.infrastructure.database.models import ChatToolEventModel

    event = ChatToolEventModel(
        id=7,
        conversation_id=1,
        message_id=2,
        kind="plan",
        title="一次函数训练",
        status="pending",
        tool_name="prepare_generation_plan",
        tool_call_id="call-plan",
        operation_id="",
        content_json=(
            '{"course_name":"八年级上册数学","document_name":"教材.pdf",'
            '"chapter_names":["第12章 一次函数"],"difficulty":4,'
            '"total_count":2,"question_type_counts":{"单项选择题":1,"填空题":1},'
            '"include_answers":true,"assemble_paper":true,"export_word":false}'
        ),
    )
    card = ToolExecutionCard(event)
    buttons = {button.text() for button in card.findChildren(QPushButton)}
    labels = "\n".join(label.text() for label in card.findChildren(QLabel))

    assert {"确认执行", "取消"} <= buttons
    assert "第12章 一次函数" in labels
    assert "选择题1道、填空题1道" in labels
    assert "content_json" not in labels
    card.show()
    application.processEvents()
    assert card.width() <= 760
    card.close()


def test_main_window_contains_ai_chat_navigation(tmp_path) -> None:
    _application = QApplication.instance() or QApplication([])
    from edu_exam_agent.app.bootstrap import bootstrap

    context = bootstrap(tmp_path / "config.toml")
    window = MainWindow(context)

    labels = [button.text() for button in window._buttons]
    assert any("AI 对话" in label for label in labels)
    chat_index = window._page_keys.index("chat")
    chat_page = window._pages.widget(chat_index)
    assert isinstance(chat_page, ChatPage)
    window.close()


def test_chat_worker_delivers_ui_callbacks_on_main_thread(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    engine = create_database_engine(tmp_path / "chat-thread.db")
    initialize_database(engine)

    class FakeProviders:
        def get_default(self) -> ProviderConfig:
            return ProviderConfig(
                "测试服务",
                "https://example.test",
                "thread-check-model",
                True,
            )

    class ProgressAgent:
        def send_message(
            self,
            conversation_id,
            _content,
            _should_cancel,
            progress,
        ) -> ChatResponse:
            progress({"status": "running", "current_stage": "线程检查"})
            return ChatResponse(
                conversation_id,
                1,
                "线程检查完成",
                "thread-check-model",
            )

        def list_events(self, _conversation_id):
            return []

    class StatusProbe:
        def __init__(self) -> None:
            self.callback_threads: list[QThread] = []

        def setText(self, _text: str) -> None:
            self.callback_threads.append(QThread.currentThread())

    providers = FakeProviders()
    page = ChatPage(
        ChatService(engine, providers),  # type: ignore[arg-type]
        providers,  # type: ignore[arg-type]
        ProgressAgent(),  # type: ignore[arg-type]
    )
    status_probe = StatusProbe()
    page.request_status = status_probe  # type: ignore[assignment]

    page._start_request("请查询教材并出题", regenerate=False)
    deadline = time.monotonic() + 3
    while (page._active_token is not None or page._jobs) and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    application.processEvents()

    assert page._active_token is None
    assert not page._jobs
    assert len(status_probe.callback_threads) == 3
    assert all(
        thread is application.thread() for thread in status_probe.callback_threads
    )
    page.close()
