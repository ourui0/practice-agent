"""Material Design 3 inspired visual tokens for the desktop application."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_light_theme(application: QApplication) -> None:
    """Force a stable light palette even when Windows uses dark application mode."""
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#FFFFFF",
        QPalette.ColorRole.WindowText: "#202124",
        QPalette.ColorRole.Base: "#FFFFFF",
        QPalette.ColorRole.AlternateBase: "#F8F9FA",
        QPalette.ColorRole.ToolTipBase: "#3C4043",
        QPalette.ColorRole.ToolTipText: "#FFFFFF",
        QPalette.ColorRole.Text: "#202124",
        QPalette.ColorRole.Button: "#FFFFFF",
        QPalette.ColorRole.ButtonText: "#202124",
        QPalette.ColorRole.BrightText: "#D93025",
        QPalette.ColorRole.Highlight: "#D2E3FC",
        QPalette.ColorRole.HighlightedText: "#202124",
        QPalette.ColorRole.PlaceholderText: "#80868B",
        QPalette.ColorRole.Link: "#1A73E8",
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
    font-family: "Segoe UI", "Microsoft YaHei", "Roboto";
    font-size: 14px;
}
QMainWindow, QWidget#appRoot {
    background: #FFFFFF;
}
QDialog, QMessageBox, QWizard, QDockWidget {
    color: #202124;
    background: #FFFFFF;
}
QStackedWidget#workspace { background: transparent; }
QWidget#sidebar {
    background: #F8F9FA;
    border-right: 1px solid #DADCE0;
}
QLabel#brand {
    font-size: 18px;
    font-weight: 600;
    color: #5F6368;
    padding: 0;
}
QLabel#navSection {
    color: #80868B;
    font-size: 11px;
    font-weight: 600;
    padding: 12px 18px 4px 18px;
}
QListWidget#navigation {
    background: transparent;
    border: none;
    outline: none;
    padding: 0 8px;
}
QListWidget#navigation::item {
    color: #3C4043;
    min-height: 42px;
    padding: 0 14px;
    margin: 2px 0;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 8px;
}
QListWidget#navigation::item:hover {
    color: #1A73E8;
    background: #E8F0FE;
}
QListWidget#navigation::item:selected {
    color: #1A73E8;
    background: #E8F0FE;
    border-left: 3px solid #1A73E8;
    font-weight: 600;
}
QLabel#pageTitle {
    color: #202124;
    font-size: 20px;
    font-weight: 600;
}
QLabel#pageSubtitle, QLabel#secondaryText {
    color: #5F6368;
    font-size: 13px;
}
QFrame#card, QGroupBox {
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 12px;
}
QGroupBox {
    margin-top: 12px;
    padding: 18px 16px 14px 16px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #3C4043;
    background: #FFFFFF;
}
QPushButton {
    min-height: 34px;
    padding: 0 18px;
    color: #1A73E8;
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover { background: #F6F9FE; border-color: #AECBFA; }
QPushButton:pressed { background: #E8F0FE; }
QPushButton:disabled { color: #9AA0A6; background: #F8F9FA; border-color: #E8EAED; }
QPushButton[primary="true"] {
    color: #FFFFFF;
    background: #1A73E8;
    border-color: #1A73E8;
}
QPushButton[primary="true"]:hover { background: #1967D2; border-color: #1967D2; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 34px;
    padding: 0 10px;
    color: #202124;
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 8px;
    selection-background-color: #D2E3FC;
}
QTextEdit, QPlainTextEdit { padding: 10px; }
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover,
QSpinBox:hover, QDoubleSpinBox:hover { border-color: #AECBFA; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus { border: 2px solid #1A73E8; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    selection-background-color: #E8F0FE;
    selection-color: #1A73E8;
    outline: none;
}
QMenu {
    color: #202124;
    background: #FFFFFF;
    border: 1px solid #DADCE0;
    padding: 6px;
}
QMenu::item { padding: 7px 24px 7px 10px; border-radius: 6px; }
QMenu::item:selected { color: #1A73E8; background: #E8F0FE; }
QMenu::separator { height: 1px; background: #E8EAED; margin: 5px 8px; }
QSlider::groove:horizontal { height: 4px; background: #DADCE0; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #1A73E8; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 18px; height: 18px; margin: -7px 0;
    background: #1A73E8; border: 3px solid #FFFFFF; border-radius: 9px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QTableWidget, QListWidget:not(#navigation), QTreeWidget {
    background: #FFFFFF;
    alternate-background-color: #F8F9FA;
    border: 1px solid #DADCE0;
    border-radius: 10px;
    gridline-color: #E8EAED;
    outline: none;
}
QAbstractScrollArea, QAbstractScrollArea::viewport {
    color: #202124;
    background: #FFFFFF;
}
QTabWidget::pane { background: #FFFFFF; border: 1px solid #DADCE0; border-radius: 8px; }
QTabBar::tab {
    color: #5F6368; background: #F8F9FA; padding: 9px 16px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: #1A73E8; background: #FFFFFF; border-bottom-color: #1A73E8; }
QProgressBar {
    color: #5F6368; background: #F1F3F4; border: none; border-radius: 4px;
    text-align: center; min-height: 8px;
}
QProgressBar::chunk { background: #1A73E8; border-radius: 4px; }
QSplitter::handle { background: #E8EAED; }
QHeaderView::section {
    color: #5F6368;
    background: #F8F9FA;
    border: none;
    border-bottom: 1px solid #DADCE0;
    padding: 10px 8px;
    font-weight: 600;
}
QTableWidget::item { padding: 8px; border-bottom: 1px solid #F1F3F4; }
QTableWidget::item:selected, QListWidget::item:selected {
    color: #202124; background: #E8F0FE;
}
QScrollBar:vertical { width: 10px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { min-height: 30px; background: #DADCE0; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #BDC1C6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { color: #5F6368; background: #F8F9FA; border-top: 1px solid #E8EAED; }
QToolTip { color: #FFFFFF; background: #3C4043; border: none; padding: 6px; }
"""
