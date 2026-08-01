from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout

from edu_exam_agent.ui.theme import GOOGLE_WORKSPACE_QSS
from edu_exam_agent.ui.widgets import NavigationButton


def _render_at_scale(widget: QFrame, scale: float) -> QImage:
    size = widget.size()
    image = QImage(
        round(size.width() * scale),
        round(size.height() * scale),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(QColor("#FFFFFF"))
    painter = QPainter(image)
    painter.scale(scale, scale)
    widget.render(painter, QPoint())
    painter.end()
    return image


def _contains_focus_blue(image: QImage) -> bool:
    focus_blue = QColor("#0B57D0")
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            distance = (
                abs(pixel.red() - focus_blue.red())
                + abs(pixel.green() - focus_blue.green())
                + abs(pixel.blue() - focus_blue.blue())
            )
            if pixel.alpha() > 220 and distance < 24:
                return True
    return False


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5])
def test_sidebar_navigation_focus_has_no_square_blue_outline(scale: float) -> None:
    application = QApplication.instance() or QApplication([])
    sidebar = QFrame()
    sidebar.setObjectName("Sidebar")
    sidebar.setFixedSize(360, 88)
    sidebar.setStyleSheet(GOOGLE_WORKSPACE_QSS)

    layout = QVBoxLayout(sidebar)
    layout.setContentsMargins(0, 8, 0, 8)
    button = NavigationButton("教材管理", sidebar)
    layout.addWidget(button)

    sidebar.show()
    application.processEvents()
    geometry_before = button.geometry()

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    button.set_active(True)
    button.setFocus(Qt.FocusReason.TabFocusReason)
    application.processEvents()

    assert button.hasFocus()
    assert button.focusPolicy() != Qt.FocusPolicy.NoFocus
    assert button.property("navButton") is True
    assert button.property("active") is True
    assert button.geometry() == geometry_before

    rendered = _render_at_scale(sidebar, scale)
    assert not _contains_focus_blue(rendered)
    sidebar.close()


def test_sidebar_focus_override_is_scoped_after_global_button_focus_rule() -> None:
    global_rule = "QPushButton:focus {"
    scoped_rule = (
        'QFrame#Sidebar QPushButton#NavButton[navButton="true"]:focus,'
    )

    assert global_rule in GOOGLE_WORKSPACE_QSS
    assert scoped_rule in GOOGLE_WORKSPACE_QSS
    assert GOOGLE_WORKSPACE_QSS.index(scoped_rule) > GOOGLE_WORKSPACE_QSS.index(global_rule)
