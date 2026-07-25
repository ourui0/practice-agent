from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\出题助手\src")
sys.path.append(r"D:\出题助手\.venv\Lib\site-packages")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from edu_exam_agent.ui.pages.generation_pages import ExamGenerationPage
from edu_exam_agent.ui.theme import apply_light_theme


class _Courses:
    def list(self):
        return [SimpleNamespace(id=1, name="沪科版八年级数学")]


class _Documents:
    def list(self, _course_id):
        return [
            SimpleNamespace(
                id=1,
                filename="【沪科版】八年级下册数学电子课本.pdf",
                parse_status="completed",
            )
        ]

    def chapter_outline(self, _document_id):
        return ()


class _EmptyService:
    def list(self, *_args, **_kwargs):
        return []


app = QApplication([])
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
app.setFont(QFont("Microsoft YaHei", 10))
apply_light_theme(app)
app.setStyleSheet(
    app.styleSheet().replace(
        '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif',
        '"Microsoft YaHei"',
    )
)
page = ExamGenerationPage(
    _Courses(),
    _Documents(),
    _EmptyService(),
    _EmptyService(),
    None,
    None,
    _EmptyService(),
)
page.resize(1180, 820)
page.show()
page.page_scroll.ensureWidgetVisible(page.type_count_card, 0, 24)
app.processEvents()

output = Path(r"D:\出题助手\output\题型数量配置界面.png")
output.parent.mkdir(parents=True, exist_ok=True)
assert page.grab().save(str(output))
print(output)
