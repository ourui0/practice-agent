"""High-scoring recommendations presented as breathable Material cards."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from edu_exam_agent.application.services.course_service import CourseService
from edu_exam_agent.application.services.question_bank_service import QuestionBankService
from edu_exam_agent.ui.widgets import GlowCard


class RealRecommendationPage(QWidget):
    def __init__(self, courses: CourseService, bank: QuestionBankService) -> None:
        super().__init__()
        self._courses = courses
        self._bank = bank

        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 34, 42, 30)
        layout.setSpacing(18)

        title = QLabel("智能推荐")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("综合题目质量与难度适配度，从真实题库中筛选适合当前教学目标的题目。")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        filters = GlowCard()
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(20, 16, 20, 16)
        filter_layout.setSpacing(14)
        self.course = QComboBox()
        self.course.setMinimumWidth(180)
        self.course.setAccessibleName("课程范围")
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.difficulty.setValue(3)
        self.difficulty.setPrefix("难度  ")
        self.minimum = QSlider(Qt.Orientation.Horizontal)
        self.minimum.setRange(0, 100)
        self.minimum.setValue(75)
        self.minimum.setMinimumWidth(170)
        self.minimum_value = QLabel("最低综合分  75")
        self.minimum_value.setObjectName("secondaryText")
        self.minimum.valueChanged.connect(
            lambda value: self.minimum_value.setText(f"最低综合分  {value}")
        )
        button = QPushButton("推荐高分题目")
        button.setProperty("primary", True)
        button.clicked.connect(self.refresh)
        filter_layout.addWidget(QLabel("课程"))
        filter_layout.addWidget(self.course)
        filter_layout.addWidget(self.minimum_value)
        filter_layout.addWidget(self.minimum, 1)
        filter_layout.addWidget(self.difficulty)
        filter_layout.addWidget(button)
        layout.addWidget(filters)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("recommendationScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.card_host = QWidget()
        self.card_host.setStyleSheet("background: transparent;")
        self.card_layout = QVBoxLayout(self.card_host)
        self.card_layout.setContentsMargins(0, 2, 4, 2)
        self.card_layout.setSpacing(12)
        self.card_layout.addStretch(1)
        self.scroll.setWidget(self.card_host)
        layout.addWidget(self.scroll, 1)
        self.status = QLabel()
        self.status.setObjectName("secondaryText")
        layout.addWidget(self.status)
        self.reload_courses()

    def reload_courses(self) -> None:
        current = self.course.currentData()
        self.course.blockSignals(True)
        self.course.clear()
        for course in self._courses.list():
            self.course.addItem(course.name, course.id)
        index = self.course.findData(current)
        if index >= 0:
            self.course.setCurrentIndex(index)
        self.course.blockSignals(False)

    def refresh(self) -> None:
        questions = self._bank.list(
            course_id=self.course.currentData(),
            difficulty=self.difficulty.value(),
            minimum_score=self.minimum.value(),
        )
        while self.card_layout.count() > 1:
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for question in questions:
            self.card_layout.insertWidget(
                self.card_layout.count() - 1, self._question_card(question)
            )
        self.status.setText(f"已推荐 {len(questions)} 道题，按综合得分从高到低排列。")

    @staticmethod
    def _question_card(question) -> GlowCard:  # type: ignore[no-untyped-def]
        card = GlowCard()
        card.setMinimumHeight(116)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        kind = QLabel(f"{question.question_type}  ·  难度 {question.difficulty}")
        kind.setObjectName("secondaryText")
        badge = QLabel(f"{question.recommendation_score:g} 分")
        badge.setObjectName("ScoreBadge")
        badge.setToolTip(
            f"题目质量 {question.quality_score * 100:.0f}% · "
            "综合评分按质量与难度适配计算"
        )
        header.addWidget(kind)
        header.addStretch(1)
        header.addWidget(badge)
        layout.addLayout(header)

        stem = QLabel(question.stem)
        stem.setWordWrap(True)
        stem.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(stem)
        number = QLabel(f"题目 #{question.id}")
        number.setObjectName("secondaryText")
        layout.addWidget(number)
        return card
