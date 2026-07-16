"""Reusable presentation widgets."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QRadialGradient
from PySide6.QtWidgets import QFrame, QWidget


class GoogleGlowWidget(QWidget):
    """White workspace with a restrained radial glow following the pointer."""

    def __init__(self, parent: QWidget | None = None, radius: int = 180) -> None:
        super().__init__(parent)
        self._mouse_position = QPoint(-1000, -1000)
        self._glow_radius = radius
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse_position = event.position().toPoint()
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._mouse_position = QPoint(-1000, -1000)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        if self.rect().contains(self._mouse_position):
            gradient = QRadialGradient(self._mouse_position, self._glow_radius)
            gradient.setColorAt(0.0, QColor(241, 243, 244, 153))
            gradient.setColorAt(0.55, QColor(232, 240, 254, 55))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRect(self.rect())
        painter.end()


class GlowCard(QFrame):
    """Rounded card variant using the same quiet pointer-following glow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._mouse_position = QPoint(-1000, -1000)
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse_position = event.position().toPoint()
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._mouse_position = QPoint(-1000, -1000)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.rect().contains(self._mouse_position):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QRadialGradient(self._mouse_position, 150)
        gradient.setColorAt(0.0, QColor(241, 243, 244, 150))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
