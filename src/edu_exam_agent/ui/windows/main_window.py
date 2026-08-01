"""Material navigation shell for teacher-facing workflows."""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.app.bootstrap import ApplicationContext
from edu_exam_agent.app.icon import application_icon
from edu_exam_agent.application.agent_tools import (
    AgentToolRegistry,
    TaskControlRegistry,
    ToolExecutionContext,
)
from edu_exam_agent.application.services.chat_agent_service import ChatAgentService
from edu_exam_agent.application.services.chat_service import ChatService
from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import KnowledgePointService
from edu_exam_agent.application.services.paper_service import PaperService
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.infrastructure.security import SecretStore
from edu_exam_agent.ui.pages.chat_page import ChatPage
from edu_exam_agent.ui.pages.course_page import CoursePage
from edu_exam_agent.ui.pages.generation_pages import ExamGenerationPage, PracticeGenerationPage
from edu_exam_agent.ui.pages.knowledge_point_page import KnowledgePointPage
from edu_exam_agent.ui.pages.material_page import MaterialPage
from edu_exam_agent.ui.pages.model_settings_page import ModelSettingsPage
from edu_exam_agent.ui.pages.question_bank_page import QuestionBankPage
from edu_exam_agent.ui.pages.recommendation_page import RealRecommendationPage
from edu_exam_agent.ui.pages.single_question_page import SingleQuestionPage
from edu_exam_agent.ui.pages.teaching_package_page import TeachingPackagePage
from edu_exam_agent.ui.theme import ANIMATION_DURATION_NORMAL, GOOGLE_WORKSPACE_QSS
from edu_exam_agent.ui.widgets import NavigationButton


class _TabbedPage(QWidget):
    """One navigation destination containing closely related business pages."""

    def __init__(self, tabs: tuple[tuple[str, QWidget], ...]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 24)
        tab_widget = QTabWidget()
        for label, page in tabs:
            tab_widget.addTab(page, label)
        layout.addWidget(tab_widget)
        self._pages = tuple(page for _, page in tabs)

    def reload_courses(self) -> None:
        for page in self._pages:
            reload_courses = getattr(page, "reload_courses", None)
            if callable(reload_courses):
                reload_courses()

    def load_paper(self, history_id: int) -> None:
        for page in self._pages:
            load_paper = getattr(page, "load_paper", None)
            if callable(load_paper):
                load_paper(history_id)
                return


class MainWindow(QMainWindow):
    """Grouped pill navigation and a static, cool-white workspace."""

    NAVIGATION = (
        (
            "备课准备",
            (
                ("📚  教材管理", "materials"),
                ("🏷  知识点管理", "knowledge_points"),
                ("◎  教材追踪", "teaching_packages"),
            ),
        ),
        (
            "出题组卷",
            (
                ("✦  单题生成", "single"),
                ("💬  AI 对话", "chat"),
                ("💡  智能推荐", "recommendations"),
                ("📄  试卷组装", "assembly"),
            ),
        ),
        (
            "资源与设置",
            (
                ("▦  题库", "question_bank"),
                ("◇  课程管理", "courses"),
                ("⚙  配置与设置", "settings"),
            ),
        ),
    )

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__()
        self._context = context
        self._buttons: list[NavigationButton] = []
        self._page_keys: list[str] = []
        self._active_section_label: QLabel | None = None
        self._section_labels: dict[str, QLabel] = {}
        self._page_section_map: dict[str, str] = {}
        self._transition_anim: QPropertyAnimation | None = None
        self._fade_in_anim: QPropertyAnimation | None = None
        self.setWindowTitle(context.config.app.name)
        self.setWindowIcon(application_icon())
        self.resize(1280, 800)
        self.setMinimumSize(1040, 680)
        self.setStyleSheet(GOOGLE_WORKSPACE_QSS)
        self._build_ui()
        self._install_shortcuts()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        pages_by_key = self._create_pages()
        self._page_keys = [
            key for _, entries in self.NAVIGATION for _, key in entries
        ]
        pages = QStackedWidget()
        pages.setObjectName("workspaceSurface")
        for key in self._page_keys:
            pages.addWidget(pages_by_key[key])

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 24, 0, 16)
        sidebar_layout.setSpacing(4)

        brand = QLabel(
            '<span style="color:#444746">EduExam</span> '
            '<span style="color:#0B57D0">Agent</span>'
        )
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setContentsMargins(28, 0, 20, 18)
        sidebar_layout.addWidget(brand)

        page_index = 0
        for section_name, entries in self.NAVIGATION:
            section = QLabel(section_name)
            section.setObjectName("navSection")
            sidebar_layout.addWidget(section)
            for label, key in entries:
                button = NavigationButton(label)
                index = page_index
                button.clicked.connect(
                    lambda _checked=False, value=index: self._select_page(value)
                )
                sidebar_layout.addWidget(button)
                self._buttons.append(button)
                self._page_section_map[key] = section_name
                page_index += 1
        sidebar_layout.addStretch(1)
        footer = QLabel("教材边界 · 智能组题 · 本地题库")
        footer.setObjectName("secondaryText")
        footer.setWordWrap(True)
        footer.setContentsMargins(28, 10, 20, 0)
        sidebar_layout.addWidget(footer)

        self._pages = pages
        self._sidebar = sidebar
        root_layout.addWidget(sidebar)
        root_layout.addWidget(pages, 1)
        self.setCentralWidget(root)
        self._update_context_status()
        self._select_page(0)

    def _create_pages(self) -> dict[str, QWidget]:
        courses = CourseService(self._context.engine)
        documents = DocumentService(self._context.engine)
        knowledge = KnowledgePointService(self._context.engine)
        bank = QuestionBankService(self._context.engine)
        providers = ProviderService(
            self._context.engine,
            SecretStore(self._context.paths.data_dir / "secrets.dat"),
        )
        retriever = FtsRetriever(self._context.engine)
        papers = PaperService(bank)
        chat_service = ChatService(self._context.engine, providers)
        tool_context = ToolExecutionContext(
            engine=self._context.engine,
            courses=courses,
            documents=documents,
            knowledge_points=knowledge,
            bank=bank,
            papers=papers,
            providers=providers,
            retriever=retriever,
            output_dir=self._context.paths.data_dir / "exports",
            task_controls=TaskControlRegistry(),
        )
        tool_registry = AgentToolRegistry(tool_context)
        chat_agent = ChatAgentService(
            self._context.engine,
            providers,
            chat_service,
            tool_registry,
            tool_context,
        )
        chat = ChatPage(chat_service, providers, chat_agent)
        chat.settings_requested.connect(
            lambda: self._select_page(self._page_keys.index("settings"))
        )
        question_bank_page = QuestionBankPage(courses, bank)
        chat.open_question_bank_requested.connect(
            lambda ids: self._open_generated_questions(question_bank_page, ids)
        )
        chat.open_paper_requested.connect(self._open_generated_paper)
        chat.open_course_requested.connect(
            lambda _course_id: self._select_page(self._page_keys.index("courses"))
        )
        chat.open_material_requested.connect(
            lambda _document_id: self._select_page(self._page_keys.index("materials"))
        )

        exam = ExamGenerationPage(
            courses, documents, knowledge, providers, retriever, self._context.engine, papers
        )
        practice = PracticeGenerationPage(
            courses, documents, knowledge, providers, retriever, self._context.engine, papers
        )
        settings = _TabbedPage(
            (
                ("模型服务", ModelSettingsPage(providers)),
                ("系统设置", self._system_settings_page()),
            )
        )
        return {
            "materials": MaterialPage(courses, documents, retriever),
            "knowledge_points": KnowledgePointPage(courses, knowledge),
            "teaching_packages": TeachingPackagePage(
                courses,
                documents,
                knowledge,
                providers,
                retriever,
                self._context.engine,
            ),
            "recommendations": RealRecommendationPage(courses, bank),
            "assembly": _TabbedPage((("正式试卷", exam), ("训练习题", practice))),
            "single": SingleQuestionPage(
                courses, knowledge, providers, retriever, self._context.engine
            ),
            "chat": chat,
            "question_bank": question_bank_page,
            "courses": CoursePage(courses),
            "settings": settings,
        }

    def _open_generated_questions(
        self, page: QuestionBankPage, question_ids: list[int]
    ) -> None:
        self._select_page(self._page_keys.index("question_bank"))
        page.focus_question_ids(question_ids)

    def _open_generated_paper(self, history_id: int) -> None:
        index = self._page_keys.index("assembly")
        self._select_page(index)
        page = self._pages.widget(index)
        load_paper = getattr(page, "load_paper", None)
        if callable(load_paper):
            load_paper(history_id)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _select_page(self, index: int) -> None:
        if index < 0 or index >= len(self._page_keys):
            return
        # Animate transition
        current_widget = self._pages.currentWidget()
        target_widget = self._pages.widget(index)
        if current_widget is not None and current_widget is not target_widget:
            self._crossfade(current_widget, target_widget, index)
        else:
            self._pages.setCurrentIndex(index)
        # Update nav button states
        for button_index, button in enumerate(self._buttons):
            button.set_active(button_index == index)
        # Highlight active section label
        key = self._page_keys[index]
        section_name = self._page_section_map.get(key)
        self._highlight_section(section_name)
        # Reload courses on the target page
        page = target_widget
        reload_courses = getattr(page, "reload_courses", None)
        if callable(reload_courses):
            reload_courses()
        self._update_context_status()

    def _crossfade(
        self, from_widget: QWidget, to_widget: QWidget, target_index: int
    ) -> None:
        """Fade out current page, switch, fade in target page."""
        # Clean up any in-progress animation and its effect to prevent
        # QGraphicsOpacityEffect leaks that leave widgets invisible but
        # still clickable.
        if self._transition_anim is not None:
            self._transition_anim.stop()
            # The previous fade-out target may still have an opacity effect;
            # walk all stacked pages and clear stale effects.
            for i in range(self._pages.count()):
                w = self._pages.widget(i)
                if w is not None and w is not to_widget:
                    effect = w.graphicsEffect()
                    if isinstance(effect, QGraphicsOpacityEffect):
                        w.setGraphicsEffect(None)
            self._transition_anim = None

        opacity_effect = QGraphicsOpacityEffect(from_widget)
        opacity_effect.setOpacity(1.0)
        from_widget.setGraphicsEffect(opacity_effect)
        self._transition_anim = QPropertyAnimation(opacity_effect, b"opacity")
        self._transition_anim.setDuration(ANIMATION_DURATION_NORMAL)
        self._transition_anim.setStartValue(1.0)
        self._transition_anim.setEndValue(0.0)
        self._transition_anim.finished.connect(
            lambda: self._finish_crossfade(from_widget, to_widget, target_index)
        )
        self._transition_anim.start()

    def _finish_crossfade(
        self, from_widget: QWidget, to_widget: QWidget, target_index: int
    ) -> None:
        from_widget.setGraphicsEffect(None)
        self._pages.setCurrentIndex(target_index)
        self._transition_anim = None
        # Fade in
        opacity_effect = QGraphicsOpacityEffect(to_widget)
        opacity_effect.setOpacity(0.0)
        to_widget.setGraphicsEffect(opacity_effect)
        self._fade_in_anim = QPropertyAnimation(opacity_effect, b"opacity")
        self._fade_in_anim.setDuration(ANIMATION_DURATION_NORMAL)
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)

        def _cleanup_fade_in() -> None:
            to_widget.setGraphicsEffect(None)
            self._fade_in_anim = None

        self._fade_in_anim.finished.connect(_cleanup_fade_in)
        self._fade_in_anim.start()

    def _highlight_section(self, section_name: str | None) -> None:
        """Brighten the nav-section label whose child is active."""
        for label in self._sidebar.findChildren(QLabel):
            if label.objectName() == "navSection":
                if section_name is not None and label.text() == section_name:
                    label.setStyleSheet(
                        "color: #0B57D0; font-size: 11px; font-weight: 600;"
                        "padding: 13px 14px 4px 14px;"
                    )
                else:
                    label.setStyleSheet("")  # revert to QSS default

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_context_status(self) -> None:
        """Reflect current course context in the status bar."""
        try:
            course_list = CourseService(self._context.engine).list()
        except Exception:
            self.statusBar().showMessage("数据目录：" + str(self._context.paths.data_dir))
            return
        active = [c for c in course_list if not c.is_archived]
        if not active:
            self.statusBar().showMessage(
                "还没有课程，请先在「课程管理」中创建课程 | "
                + str(self._context.paths.data_dir)
            )
            return
        # Show first active course as context
        course = active[0]
        try:
            bank = QuestionBankService(self._context.engine)
            question_count = len(bank.list(course.id))
        except Exception:
            question_count = 0
        try:
            documents = DocumentService(self._context.engine)
            doc_list = documents.list(course.id)
            doc_count = len(doc_list)
        except Exception:
            doc_count = 0
        self.statusBar().showMessage(
            f"当前课程：{course.name} | 题库 {question_count} 题 | 教材 {doc_count} 本"
        )

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _install_shortcuts(self) -> None:
        """Register global keyboard shortcuts."""
        # Ctrl+1 … Ctrl+9 → navigate to N-th page
        for index in range(min(9, len(self._page_keys))):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(
                lambda idx=index: self._select_page(idx)
            )

        # Ctrl+F → focus search box on current page
        focus_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        focus_shortcut.activated.connect(self._focus_current_search)

        # F5 → refresh current page
        refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        refresh_shortcut.activated.connect(self._refresh_current_page)

        # Delete → trigger delete on current page
        del_shortcut = QShortcut(QKeySequence("Delete"), self)
        del_shortcut.activated.connect(self._delete_current_selection)

        # Ctrl+E → export on assembly page
        export_shortcut = QShortcut(QKeySequence("Ctrl+E"), self)
        export_shortcut.activated.connect(self._export_current_paper)

        # Ctrl+Z → undo (placeholder — UndoManager not yet wired)
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(self._undo_last_action)

        # Escape → close popup / dialog
        esc_shortcut = QShortcut(QKeySequence("Escape"), self)
        esc_shortcut.activated.connect(self._escape_current)

    def _current_page(self) -> QWidget | None:
        idx = self._pages.currentIndex()
        if 0 <= idx < len(self._page_keys):
            return self._pages.widget(idx)
        return None

    def _focus_current_search(self) -> None:
        page = self._current_page()
        if page is None:
            return
        # Walk children looking for a QLineEdit used as search
        for child in page.findChildren(QWidget):
            from PySide6.QtWidgets import QLineEdit
            if isinstance(child, QLineEdit) and child.isVisible():
                placeholder = child.placeholderText()
                if placeholder and any(
                    kw in placeholder for kw in ("搜索", "检索", "关键词")
                ):
                    child.setFocus()
                    return

    def _refresh_current_page(self) -> None:
        page = self._current_page()
        if page is None:
            return
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _delete_current_selection(self) -> None:
        page = self._current_page()
        if page is None:
            return
        delete_method = getattr(page, "_delete", None)
        if callable(delete_method):
            delete_method()

    def _export_current_paper(self) -> None:
        page = self._current_page()
        if page is None:
            return
        export = getattr(page, "export", None)
        if callable(export):
            export()

    def _undo_last_action(self) -> None:
        # Placeholder — full UndoManager integration is P2
        page = self._current_page()
        if page is None:
            return
        undo = getattr(page, "undo", None)
        if callable(undo):
            undo()

    def _escape_current(self) -> None:
        from PySide6.QtWidgets import QApplication, QDialog
        # Close any active popup / dialog
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                widget.reject()
                return
        # Hide chapter popup on assembly pages
        page = self._current_page()
        if page is not None:
            popup = getattr(page, "chapter_popup", None)
            if popup is not None and popup.isVisible():
                popup.hide()

    # ------------------------------------------------------------------
    # System settings placeholder
    # ------------------------------------------------------------------

    @staticmethod
    def _system_settings_page() -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(12)
        title = QLabel("系统设置")
        title.setObjectName("pageTitle")
        subtitle = QLabel("备份恢复、诊断日志与更新管理将在后续阶段接入。")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return page
