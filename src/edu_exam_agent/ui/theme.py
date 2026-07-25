"""Google Material 3 visual tokens and a Windows-stable light palette."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

WINDOW_BASE = "#F8F9FA"
SURFACE = "#FFFFFF"
FIELD_FILL = "#FFFFFF"
PRIMARY = "#0B57D0"
TEXT = "#202124"
SECONDARY_TEXT = "#5F6368"
OUTLINE = "#E0E3E7"


def apply_light_theme(application: QApplication) -> None:
    """Force the Material light palette even when Windows application mode is dark."""
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: WINDOW_BASE,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: "#F7F9FC",
        QPalette.ColorRole.ToolTipBase: "#3C4043",
        QPalette.ColorRole.ToolTipText: SURFACE,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: SURFACE,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: "#D93025",
        QPalette.ColorRole.Highlight: "#D3E3FD",
        QPalette.ColorRole.HighlightedText: "#041E49",
        QPalette.ColorRole.PlaceholderText: "#80868B",
        QPalette.ColorRole.Link: PRIMARY,
        QPalette.ColorRole.LinkVisited: "#681DA8",
    }
    for role, color in colors.items():
        palette.setColor(QPalette.ColorGroup.All, role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#9AA0A6"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#9AA0A6")
    )
    application.setPalette(palette)
    application.setStyleSheet(GOOGLE_WORKSPACE_QSS)


GOOGLE_WORKSPACE_QSS = r"""
QWidget {
    color: #202124;
    background: transparent;
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#appRoot, QWidget#workspaceSurface {
    background: #F8F9FA;
}
QDialog, QMessageBox, QWizard, QDockWidget {
    color: #202124;
    background: #F8F9FA;
}
QFrame#Sidebar {
    background: #FFFFFF;
    border: none;
}
QLabel#brand {
    color: #444746;
    font-size: 19px;
    font-weight: 600;
}
QLabel#navSection {
    color: #747775;
    font-size: 11px;
    font-weight: 600;
    padding: 13px 14px 4px 14px;
}
QPushButton#NavButton {
    min-height: 40px;
    max-height: 40px;
    margin: 4px 12px;
    padding: 0 20px;
    color: #444746;
    background: transparent;
    border: none;
    border-radius: 20px;
    text-align: left;
    font-weight: 500;
}
QPushButton#NavButton:hover {
    color: #1F1F1F;
    background: #F1F3F4;
}
QPushButton#NavButton[active="true"] {
    color: #041E49;
    background: #D3E3FD;
    font-weight: 600;
}
QLabel#pageTitle {
    color: #1F1F1F;
    font-size: 22px;
    font-weight: 600;
}
QLabel#pageSubtitle, QLabel#secondaryText {
    color: #5F6368;
    font-size: 13px;
}
QFrame#StandardCard, QFrame#GlowCard, QGroupBox {
    background: #FFFFFF;
    border: 1px solid #E0E3E7;
    border-radius: 12px;
}
QFrame#OutlineCard {
    background: #FFFFFF;
    border: 1px solid #E0E3E7;
    border-radius: 12px;
}
QFrame#OutlineCard QLabel#cardTitle {
    color: #1F1F1F;
    font-size: 16px;
    font-weight: 600;
}
QFrame#OutlineCard QWidget#FormItem QLabel[formLabel="true"] {
    color: #5F6368;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}
QFrame#OutlineCard QWidget#FormItem QLineEdit,
QFrame#OutlineCard QWidget#FormItem QComboBox,
QFrame#OutlineCard QWidget#FormItem QSpinBox,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox {
    min-height: 36px;
    max-height: 36px;
    padding: 2px 12px;
    color: #1F1F1F;
    background-color: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
}
QFrame#OutlineCard QWidget#FormItem QLineEdit:hover,
QFrame#OutlineCard QWidget#FormItem QComboBox:hover,
QFrame#OutlineCard QWidget#FormItem QSpinBox:hover,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox:hover {
    border-color: #80868B;
}
QFrame#OutlineCard QWidget#FormItem QLineEdit:focus,
QFrame#OutlineCard QWidget#FormItem QComboBox:focus,
QFrame#OutlineCard QWidget#FormItem QSpinBox:focus,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox:focus {
    padding: 2px 11px;
    border: 2px solid #0B57D0;
}
QFrame#OutlineCard QWidget#FormItem QComboBox QLineEdit,
QFrame#OutlineCard QWidget#FormItem QSpinBox QLineEdit,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox QLineEdit {
    min-height: 0;
    max-height: 16777215px;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: 0;
}
QFrame#OutlineCard QWidget#FormItem QSpinBox::up-button,
QFrame#OutlineCard QWidget#FormItem QSpinBox::down-button,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox::up-button,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox::down-button {
    width: 0;
    height: 0;
    margin: 0;
    padding: 0;
    background: transparent;
    border: none;
}
QFrame#OutlineCard QWidget#FormItem QSpinBox::up-arrow,
QFrame#OutlineCard QWidget#FormItem QSpinBox::down-arrow,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox::up-arrow,
QFrame#OutlineCard QWidget#FormItem QDoubleSpinBox::down-arrow {
    width: 0;
    height: 0;
    image: none;
}
QFrame#OutlineCard QWidget#FormItem QComboBox QAbstractItemView {
    color: #202124;
    background-color: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    selection-color: #041E49;
    selection-background-color: #D3E3FD;
    outline: none;
}
QScrollArea#paperGenerationScroll,
QScrollArea#paperGenerationScroll::viewport,
QWidget#paperGenerationContent {
    background: #FFFFFF;
    border: none;
}
QPushButton#ChapterSelectButton {
    min-height: 38px;
    max-height: 38px;
    padding: 0 12px;
    color: #1F1F1F;
    background-color: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    text-align: left;
    font-weight: 400;
}
QPushButton#ChapterSelectButton:hover {
    background-color: #F8FAFD;
    border-color: #AAB0B6;
}
QPushButton#ChapterSelectButton:focus {
    padding: 0 11px;
    border: 2px solid #0B57D0;
}
QPushButton#ChapterSelectButton:disabled {
    color: #9AA0A6;
    background-color: #F1F3F4;
    border-color: #DADCE0;
}
QFrame#ChapterPopup {
    background-color: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 12px;
}
QFrame#ChapterPopup QLabel[chapterColumnLabel="true"] {
    color: #5F6368;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
}
QFrame#ChapterPopup QListWidget {
    padding: 4px;
    background-color: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    outline: none;
}
QFrame#ChapterPopup QListWidget::item {
    padding: 7px 8px;
    border-radius: 6px;
}
QFrame#ChapterPopup QListWidget::item:selected {
    color: #041E49;
    background: #D3E3FD;
}
QFrame#OutlineCard QCheckBox { spacing: 8px; }
QGroupBox {
    margin-top: 13px;
    padding: 20px 18px 16px 18px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 7px;
    color: #444746;
    background: #FFFFFF;
}
QPushButton {
    min-height: 40px;
    padding: 0 20px;
    color: #0B57D0;
    background: #FFFFFF;
    border: 1px solid #C4C7C5;
    border-radius: 20px;
    font-weight: 600;
}
QPushButton:hover { background: #F6F9FE; border-color: #AECBFA; }
QPushButton:pressed { background: #E8F0FE; }
QPushButton:disabled { color: #9AA0A6; background: #F1F3F4; border-color: #E3E3E3; }
QPushButton[primary="true"] {
    color: #FFFFFF;
    background: #0B57D0;
    border-color: #0B57D0;
}
QPushButton[primary="true"]:hover { background: #0842A0; border-color: #0842A0; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 22px;
    padding: 10px 14px;
    color: #1F1F1F;
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    selection-background-color: #D3E3FD;
}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover,
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #80868B; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    padding: 9px 13px;
    border: 2px solid #0B57D0;
}
QComboBox::drop-down { border: none; width: 30px; }
QComboBox QAbstractItemView {
    color: #202124;
    background: #FFFFFF;
    border: 1px solid #E0E3E7;
    selection-background-color: #D3E3FD;
    selection-color: #041E49;
    outline: none;
}
QMenu {
    color: #202124;
    background: #FFFFFF;
    border: 1px solid #E0E3E7;
    padding: 6px;
}
QMenu::item { padding: 8px 26px 8px 12px; border-radius: 6px; }
QMenu::item:selected { color: #041E49; background: #D3E3FD; }
QMenu::separator { height: 1px; background: #E3E3E3; margin: 5px 8px; }
QSlider::groove:horizontal { height: 4px; background: #C4C7C5; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #0B57D0; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 20px; height: 20px; margin: -8px 0;
    background: #0B57D0; border: 3px solid #FFFFFF; border-radius: 10px;
}
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QTableWidget, QListWidget, QTreeWidget {
    color: #202124;
    background: #FFFFFF;
    alternate-background-color: #F7F9FC;
    border: 1px solid #E0E3E7;
    border-radius: 12px;
    gridline-color: #EEF0F2;
    outline: none;
}
QListWidget#paperOutline {
    background: #F1F3F4;
    border: none;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#paperOutline::item {
    min-height: 44px;
    padding: 10px;
    margin: 6px 12px;
    color: #444746;
    background: #FFFFFF;
    border: 1px solid #E0E3E7;
    border-radius: 8px;
}
QListWidget#paperOutline::item:hover {
    color: #041E49;
    background: #E8F0FE;
    border-color: #AECBFA;
}
QListWidget#paperOutline::item:selected {
    color: #041E49;
    background: #D3E3FD;
    border-color: #0B57D0;
}
QAbstractScrollArea, QAbstractScrollArea::viewport { color: #202124; background: #FFFFFF; }
QScrollArea#recommendationScroll, QScrollArea#recommendationScroll::viewport {
    background: transparent;
    border: none;
}
QTabWidget::pane { background: #FFFFFF; border: 1px solid #E0E3E7; border-radius: 12px; }
QTabBar::tab {
    min-height: 32px; padding: 5px 18px; margin: 0 3px 0 0;
    color: #5F6368; background: transparent; border-bottom: 3px solid transparent;
}
QTabBar::tab:hover { color: #1F1F1F; background: #F1F3F4; }
QTabBar::tab:selected { color: #0B57D0; background: #FFFFFF; border-bottom-color: #0B57D0; }
QProgressBar {
    color: #5F6368; background: #F1F3F4; border: none; border-radius: 4px;
    text-align: center; min-height: 8px;
}
QProgressBar::chunk { background: #0B57D0; border-radius: 4px; }
QSplitter::handle { background: transparent; width: 6px; }
QHeaderView::section {
    color: #5F6368;
    background: #F7F9FC;
    border: none;
    border-bottom: 1px solid #E0E3E7;
    padding: 11px 9px;
    font-weight: 600;
}
QTableWidget::item { padding: 9px; border-bottom: 1px solid #EEF0F2; }
QTableWidget::item:selected, QListWidget::item:selected { color: #041E49; background: #D3E3FD; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { min-height: 40px; background: #C4C7C5; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #8E918F; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { color: #5F6368; background: #FFFFFF; border-top: 1px solid #E3E3E3; }
QToolTip { color: #FFFFFF; background: #3C4043; border: none; padding: 7px; }
QLabel#ScoreBadge {
    color: #1A73E8;
    background: #E8F0FE;
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 12px;
    font-weight: 600;
}
QFrame#OutlineDrawer { background: #F1F3F4; border-left: 1px solid #E0E3E7; }
"""
