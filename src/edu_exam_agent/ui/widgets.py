"""Reusable Material presentation widgets."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NavigationButton(QPushButton):
    """Checkable navigation action with a Material pill active indicator."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("NavButton")
        self.setProperty("navButton", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)
        self.setAutoDefault(False)
        self.setDefault(False)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class GlowCard(QFrame):
    """Elevated white card with a restrained blue glow only while hovered."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GlowCard")
        self._mouse_position = QPoint(-1000, -1000)
        self._hovered = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._tracking_timer = QTimer(self)
        self._tracking_timer.setInterval(24)
        self._tracking_timer.timeout.connect(self._track_cursor)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(16)
        self._shadow.setColor(QColor(60, 64, 67, 0))
        self._shadow.setOffset(0, 2)
        self.setGraphicsEffect(self._shadow)

    def enterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = True
        self._shadow.setColor(QColor(60, 64, 67, 20))
        self._tracking_timer.start()
        self._track_cursor()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._hovered = False
        self._shadow.setColor(QColor(60, 64, 67, 0))
        self._tracking_timer.stop()
        self._mouse_position = QPoint(-1000, -1000)
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse_position = event.position().toPoint()
        self.update()
        super().mouseMoveEvent(event)

    def _track_cursor(self) -> None:
        position = self.mapFromGlobal(QCursor.pos())
        if position != self._mouse_position:
            self._mouse_position = position
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        display_rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QColor("#FFFFFF"))
        painter.setPen(
            QPen(QColor("#AECBFA"), 1.2)
            if self._hovered
            else QPen(QColor("#E0E3E7"), 1)
        )
        painter.drawRoundedRect(display_rect, 12, 12)

        if self._hovered and self.rect().contains(self._mouse_position):
            path = QPainterPath()
            path.addRoundedRect(QRectF(display_rect), 12, 12)
            painter.setClipPath(path)
            gradient = QRadialGradient(self._mouse_position, 160)
            gradient.setColorAt(0.0, QColor(11, 87, 208, 12))
            gradient.setColorAt(0.5, QColor(11, 87, 208, 4))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(display_rect)
            painter.setClipping(False)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#AECBFA"), 1.2))
            painter.drawRoundedRect(display_rect, 12, 12)
        # NOTE: Do NOT call painter.end() here — the QPainter destructor
        # handles cleanup, and explicit end() can interfere with child-widget
        # rendering on some platforms.


class StatusLabel(QLabel):
    """Unified operation-feedback label used at the bottom of every page."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusLabel")
        self.setWordWrap(True)


class EmptyStateWidget(QFrame):
    """Guidance card shown when a page has no data."""

    def __init__(
        self,
        icon: str,
        message: str,
        action_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel(icon)
        icon_label.setObjectName("EmptyStateIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        text_label = QLabel(message)
        text_label.setObjectName("EmptyStateText")
        text_label.setWordWrap(True)
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label)

        self.action_button: QPushButton | None = None
        if action_label:
            btn = QPushButton(action_label)
            btn.setProperty("primary", True)
            btn.setFixedWidth(220)
            btn_wrapper = QHBoxLayout()
            btn_wrapper.addStretch()
            btn_wrapper.addWidget(btn)
            btn_wrapper.addStretch()
            layout.addLayout(btn_wrapper)
            self.action_button = btn


def show_error(
    parent: QWidget | None,
    title: str,
    what: str,
    why: str,
    fix: str,
    detailed: str = "",
) -> QMessageBox:
    """Show a structured error dialog that teachers can understand.

    Args:
        parent: Parent widget.
        title: Short dialog title.
        what: What happened (plain language).
        why: Why it happened.
        fix: Concrete next step the user can take.
        detailed: Raw exception text, hidden behind "Details" unless expanded.
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(what)
    box.setInformativeText(f"{why}\n\n{fix}")
    if detailed:
        box.setDetailedText(detailed)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    return box


def flash_row_color(
    widget: QWidget,
    target_color: QColor,
    duration_ms: int = 500,
) -> None:
    """Briefly flash a widget's background via stylesheet, then clear."""
    original = widget.styleSheet()
    widget.setStyleSheet(
        f"background-color: {target_color.name()};"
    )
    QTimer.singleShot(duration_ms, lambda: widget.setStyleSheet(original))
