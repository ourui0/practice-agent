"""Main application shell; business pages are added incrementally."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
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
from edu_exam_agent.ui.pages.generation_pages import (
    ExamGenerationPage,
    PracticeGenerationPage,
)
from edu_exam_agent.ui.pages.knowledge_point_page import KnowledgePointPage
from edu_exam_agent.ui.pages.material_page import MaterialPage
from edu_exam_agent.ui.pages.model_settings_page import ModelSettingsPage
from edu_exam_agent.ui.pages.question_bank_page import QuestionBankPage
from edu_exam_agent.ui.pages.recommendation_page import RealRecommendationPage
from edu_exam_agent.ui.pages.single_question_page import SingleQuestionPage
from edu_exam_agent.ui.theme import GOOGLE_WORKSPACE_QSS
from edu_exam_agent.ui.widgets import GoogleGlowWidget


class MainWindow(QMainWindow):
    """Navigation shell for teacher-facing workflows."""

    PAGE_ENTRIES = (
        ("⌂  首页", "首页"),
        ("📚  教材边界", "教材管理"),
        ("💡  智能推荐", "智能推荐"),
        ("📄  正式试卷", "试卷生成"),
        ("🏋  训练习题", "训练习题生成"),
        ("✦  单题生成", "单题生成"),
        ("▦  题库", "题库"),
        ("◉  知识点", "知识点管理"),
        ("◇  课程管理", "课程管理"),
        ("⚙  模型设置", "模型设置"),
        ("⋯  系统设置", "系统设置"),
    )
    PAGE_NAMES = tuple(name for _, name in PAGE_ENTRIES)

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__()
        self._context = context
        self.setWindowTitle(context.config.app.name)
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(GOOGLE_WORKSPACE_QSS)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("appRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 22, 12, 14)
        sidebar_layout.setSpacing(8)

        brand = QLabel(
            '<span style="color:#5F6368">EduExam</span> '
            '<span style="color:#1A73E8">Agent</span>'
        )
        brand.setObjectName("brand")
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setContentsMargins(16, 0, 8, 18)
        sidebar_layout.addWidget(brand)
        section = QLabel("教师工作台")
        section.setObjectName("navSection")
        sidebar_layout.addWidget(section)

        navigation = QListWidget()
        navigation.setObjectName("navigation")
        navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, name in self.PAGE_ENTRIES:
            item = QListWidgetItem(label, navigation)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
        sidebar_layout.addWidget(navigation, 1)

        version = QLabel("专注教材边界 · 本地题库")
        version.setObjectName("secondaryText")
        version.setContentsMargins(16, 8, 8, 0)
        sidebar_layout.addWidget(version)

        workspace = GoogleGlowWidget(radius=180)
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        pages = QStackedWidget()
        pages.setObjectName("workspace")
        pages.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        implemented_pages = {
            "课程管理": lambda: CoursePage(CourseService(self._context.engine)),
            "教材管理": lambda: MaterialPage(
                CourseService(self._context.engine),
                DocumentService(self._context.engine),
                FtsRetriever(self._context.engine),
            ),
            "知识点管理": lambda: KnowledgePointPage(
                CourseService(self._context.engine),
                KnowledgePointService(self._context.engine),
            ),
            "单题生成": lambda: SingleQuestionPage(
                CourseService(self._context.engine),
                KnowledgePointService(self._context.engine),
                ProviderService(
                    self._context.engine,
                    SecretStore(self._context.paths.data_dir / "secrets.dat"),
                ),
                FtsRetriever(self._context.engine),
                self._context.engine,
            ),
            "模型设置": lambda: ModelSettingsPage(
                ProviderService(
                    self._context.engine,
                    SecretStore(self._context.paths.data_dir / "secrets.dat"),
                )
            ),
            "智能推荐": lambda: RealRecommendationPage(
                CourseService(self._context.engine),
                QuestionBankService(self._context.engine),
            ),
            "训练习题生成": lambda: PracticeGenerationPage(
                CourseService(self._context.engine),
                DocumentService(self._context.engine),
                KnowledgePointService(self._context.engine),
                ProviderService(
                    self._context.engine,
                    SecretStore(self._context.paths.data_dir / "secrets.dat"),
                ),
                FtsRetriever(self._context.engine),
                self._context.engine,
                PaperService(QuestionBankService(self._context.engine)),
            ),
            "试卷生成": lambda: ExamGenerationPage(
                CourseService(self._context.engine),
                DocumentService(self._context.engine),
                KnowledgePointService(self._context.engine),
                ProviderService(
                    self._context.engine,
                    SecretStore(self._context.paths.data_dir / "secrets.dat"),
                ),
                FtsRetriever(self._context.engine),
                self._context.engine,
                PaperService(QuestionBankService(self._context.engine)),
            ),
            "题库": lambda: QuestionBankPage(
                CourseService(self._context.engine),
                QuestionBankService(self._context.engine),
            ),
        }
        for name in self.PAGE_NAMES:
            factory = implemented_pages.get(name)
            pages.addWidget(factory() if factory else self._placeholder_page(name))
        workspace_layout.addWidget(pages)
        navigation.currentRowChanged.connect(pages.setCurrentIndex)

        def refresh_page(index: int) -> None:
            page = pages.widget(index)
            reload_courses = getattr(page, "reload_courses", None)
            if callable(reload_courses):
                reload_courses()

        navigation.currentRowChanged.connect(refresh_page)
        navigation.setCurrentRow(0)

        layout.addWidget(sidebar)
        layout.addWidget(workspace, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage(f"数据目录：{self._context.paths.data_dir}")

    @staticmethod
    def _placeholder_page(name: str) -> QWidget:
        page = GoogleGlowWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 42, 48, 42)
        title = QLabel(name)
        title.setObjectName("pageTitle")
        description = QLabel("基础工程已就绪，本模块将在后续开发阶段接入。")
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(title)
        layout.addWidget(separator)
        layout.addWidget(description)
        layout.addStretch(1)
        layout.setAlignment(title, Qt.AlignmentFlag.AlignLeft)
        return page
