"""High-scoring recommendations presented as breathable Material cards."""

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsOpacityEffect,
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
from edu_exam_agent.ui.theme import ANIMATION_DURATION_NORMAL, PAGE_MARGINS
from edu_exam_agent.ui.widgets import EmptyStateWidget, GlowCard, StatusLabel


class RealRecommendationPage(QWidget):
    def __init__(self, courses: CourseService, bank: QuestionBankService) -> None:
        super().__init__()
        self._courses = courses
        self._bank = bank

        layout = QVBoxLayout(self)
        left, top, right, bottom = PAGE_MARGINS
        layout.setContentsMargins(left, top, right, bottom)
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
        self.recommend_btn = QPushButton("推荐高分题目")
        self.recommend_btn.setProperty("primary", True)
        self.recommend_btn.clicked.connect(self.refresh)
        self.recommend_btn.setAccessibleName("推荐高分题目")
        filter_layout.addWidget(QLabel("课程"))
        filter_layout.addWidget(self.course)
        filter_layout.addWidget(self.minimum_value)
        filter_layout.addWidget(self.minimum, 1)
        filter_layout.addWidget(self.difficulty)
        filter_layout.addWidget(self.recommend_btn)
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
        self.empty_state = EmptyStateWidget(
            icon="💡",
            message="题库中还没有题目，先生成一些题目再来查看推荐",
            action_label="去生成题目 →",
        )
        self.empty_state.action_button.clicked.connect(self._navigate_to_single_question)
        self.empty_state.hide()
        layout.addWidget(self.empty_state)
        self.status_label = StatusLabel()
        layout.addWidget(self.status_label)
        self._update_button_states()
        self.reload_courses()

    def _navigate_to_single_question(self) -> None:
        window = self.window()
        if hasattr(window, "_select_page"):
            page_keys = getattr(window, "_page_keys", [])
            for i, key in enumerate(page_keys):
                if key == "single":
                    window._select_page(i)
                    return
            # Fallback: try index
            window._select_page(1)

    def _update_button_states(self) -> None:
        has_course = self.course.currentData() is not None
        self.recommend_btn.setEnabled(has_course)

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
        # Use a generation counter so stale timer callbacks (from a previous
        # refresh) bail out instead of animating already-deleted cards.
        self._card_generation = getattr(self, '_card_generation', 0) + 1
        captured_gen = self._card_generation

        while self.card_layout.count() > 1:
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        has_data = len(questions) > 0
        self.scroll.setVisible(has_data)
        self.empty_state.setVisible(not has_data and self.course.currentData() is not None)
        for i, question in enumerate(questions):
            card = self._question_card(question)
            # Staggered fade-in animation
            card_effect = QGraphicsOpacityEffect(card)
            card_effect.setOpacity(0.0)
            card.setGraphicsEffect(card_effect)
            anim = QPropertyAnimation(card_effect, b"opacity")
            anim.setDuration(ANIMATION_DURATION_NORMAL)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            QTimer.singleShot(
                i * 50,
                lambda a=anim, c=card, e=card_effect, gen=captured_gen, s=self:
                    s._start_card_anim(a, c, e, gen),
            )
            self.card_layout.insertWidget(
                self.card_layout.count() - 1, card
            )
        self.status_label.setText(
            f"已推荐 {len(questions)} 道题，按综合得分从高到低排列。"
            if questions else ""
        )

    def _start_card_anim(
        self,
        anim: QPropertyAnimation,
        card: GlowCard,
        effect: QGraphicsOpacityEffect,
        generation: int,
    ) -> None:
        # Guard: if a newer refresh() has already run, the card may be
        # queued for deletion — bail out silently.
        if getattr(self, '_card_generation', 0) != generation:
            return
        try:
            _ = card.isVisible()
        except RuntimeError:
            return

        def _finish() -> None:
            try:
                card.setGraphicsEffect(None)
            except RuntimeError:
                pass

        anim.finished.connect(_finish)
        anim.start()

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
