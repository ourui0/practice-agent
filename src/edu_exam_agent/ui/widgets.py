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
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QPushButton, QWidget


class NavigationButton(QPushButton):
    """Checkable navigation action with a Material pill active indicator."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("NavButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)

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
        painter.end()
