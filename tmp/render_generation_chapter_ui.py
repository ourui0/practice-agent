from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, r"D:\出题助手\src")
sys.path.append(r"D:\出题助手\.venv\Lib\site-packages")

from PySide6.QtWidgets import QApplication

from edu_exam_agent.application.services.document_service import (
    ChapterOutlineItem,
    ChapterOutlineSection,
)
from edu_exam_agent.ui.pages.generation_pages import PracticeGenerationPage
from edu_exam_agent.ui.theme import apply_light_theme


class Courses:
    def list(self):
        return [SimpleNamespace(id=1, name="沪科版八年级数学")]


class Documents:
    def list(self, _course_id):
        return [SimpleNamespace(id=1, filename="沪科版八年级上册.pdf", parse_status="completed")]

    def chapter_outline(self, _document_id):
        structure = {
            "第11章 平面直角坐标系": ("11.1 平面内点的坐标", "11.2 图形在坐标系中的平移"),
            "第12章 函数与一次函数": ("12.1 函数", "12.2 一次函数", "12.3 一次函数与二元一次方程"),
            "第13章 三角形中的边角关系、命题与证明": ("13.1 三角形中的边角关系", "13.2 命题与证明"),
            "第14章 全等三角形": ("14.1 全等三角形及其性质", "14.2 三角形全等的判定"),
            "第15章 轴对称图形与等腰三角形": ("15.1 轴对称图形", "15.2 线段的垂直平分线", "15.3 角的平分线", "15.4 等腰三角形"),
        }
        result = []
        next_id = 1
        for title, names in structure.items():
            sections = []
            ids = []
            for name in names:
                sections.append(ChapterOutlineSection(name, next_id))
                ids.append(next_id)
                next_id += 1
            result.append(ChapterOutlineItem(title, tuple(ids), tuple(sections)))
        return tuple(result)


class Empty:
    def list(self, *_args, **_kwargs):
        return []


app = QApplication([])
apply_light_theme(app)
page = PracticeGenerationPage(Courses(), Documents(), Empty(), Empty(), None, None, Empty())
page.resize(1024, 768)
page.show()
page.scope.setCurrentIndex(2)
root = page.chapters.item(0)
root.setSelected(True)
app.processEvents()
out = Path(r"D:\出题助手\tmp\chapter_ui_small_window.png")
page.grab().save(str(out))
page.chapter_button.click()
app.processEvents()
popup_out = Path(r"D:\出题助手\tmp\chapter_popup_debug.png")
page.chapter_popup.grab().save(str(popup_out))
spinbox_out = Path(r"D:\出题助手\tmp\spinbox_no_buttons.png")
page.count.grab().save(str(spinbox_out))
print(out)
print(popup_out)
print(spinbox_out)
