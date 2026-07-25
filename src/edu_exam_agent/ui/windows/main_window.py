"""Material navigation shell for teacher-facing workflows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.app.bootstrap import ApplicationContext
from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.document_service import DocumentService
from edu_exam_agent.application.services.knowledge_point_service import KnowledgePointService
from edu_exam_agent.application.services.paper_service import PaperService
from edu_exam_agent.application.services.provider_service import ProviderService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.infrastructure.retrieval import FtsRetriever
from edu_exam_agent.infrastructure.security import SecretStore
from edu_exam_agent.ui.pages.course_page import CoursePage
from edu_exam_agent.ui.pages.generation_pages import ExamGenerationPage, PracticeGenerationPage
from edu_exam_agent.ui.pages.knowledge_point_page import KnowledgePointPage
from edu_exam_agent.ui.pages.material_page import MaterialPage
from edu_exam_agent.ui.pages.model_settings_page import ModelSettingsPage
from edu_exam_agent.ui.pages.question_bank_page import QuestionBankPage
from edu_exam_agent.ui.pages.recommendation_page import RealRecommendationPage
from edu_exam_agent.ui.pages.single_question_page import SingleQuestionPage
from edu_exam_agent.ui.theme import GOOGLE_WORKSPACE_QSS
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


class MainWindow(QMainWindow):
    """Grouped pill navigation and a static, cool-white workspace."""

    NAVIGATION = (
        (
            "核心功能",
            (
                ("📚  教材边界", "materials"),
                ("💡  智能推荐", "recommendations"),
                ("📄  试卷组装", "assembly"),
            ),
        ),
        (
            "资源管理",
            (
                ("✦  单题生成", "single"),
                ("▦  题库与知识点", "resources"),
                ("◇  课程管理", "courses"),
            ),
        ),
        ("系统", (("⚙  配置与设置", "settings"),)),
    )

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__()
        self._context = context
        self._buttons: list[NavigationButton] = []
        self.setWindowTitle(context.config.app.name)
        self.resize(1280, 800)
        self.setMinimumSize(1040, 680)
        self.setStyleSheet(GOOGLE_WORKSPACE_QSS)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        pages_by_key = self._create_pages()
        page_order = [key for _, entries in self.NAVIGATION for _, key in entries]
        pages = QStackedWidget()
        pages.setObjectName("workspaceSurface")
        for key in page_order:
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
            for label, _ in entries:
                button = NavigationButton(label)
                index = page_index
                button.clicked.connect(lambda _checked=False, value=index: self._select_page(value))
                sidebar_layout.addWidget(button)
                self._buttons.append(button)
                page_index += 1
        sidebar_layout.addStretch(1)
        footer = QLabel("教材边界 · 智能组题 · 本地题库")
        footer.setObjectName("secondaryText")
        footer.setWordWrap(True)
        footer.setContentsMargins(28, 10, 20, 0)
        sidebar_layout.addWidget(footer)

        self._pages = pages
        root_layout.addWidget(sidebar)
        root_layout.addWidget(pages, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage(f"数据目录：{self._context.paths.data_dir}")
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

        exam = ExamGenerationPage(
            courses, documents, knowledge, providers, retriever, self._context.engine, papers
        )
        practice = PracticeGenerationPage(
            courses, documents, knowledge, providers, retriever, self._context.engine, papers
        )
        resources = _TabbedPage(
            (
                ("题库", QuestionBankPage(courses, bank)),
                ("知识点", KnowledgePointPage(courses, knowledge)),
            )
        )
        settings = _TabbedPage(
            (
                ("模型服务", ModelSettingsPage(providers)),
                ("系统设置", self._system_settings_page()),
            )
        )
        return {
            "materials": MaterialPage(courses, documents, retriever),
            "recommendations": RealRecommendationPage(courses, bank),
            "assembly": _TabbedPage((("正式试卷", exam), ("训练习题", practice))),
            "single": SingleQuestionPage(
                courses, knowledge, providers, retriever, self._context.engine
            ),
            "resources": resources,
            "courses": CoursePage(courses),
            "settings": settings,
        }

    def _select_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        for button_index, button in enumerate(self._buttons):
            button.set_active(button_index == index)
        page = self._pages.widget(index)
        reload_courses = getattr(page, "reload_courses", None)
        if callable(reload_courses):
            reload_courses()

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
