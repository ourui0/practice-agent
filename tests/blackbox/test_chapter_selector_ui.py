from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QMessageBox,
)

from edu_exam_agent.application.services.document_service import (
    ChapterOutlineItem,
    ChapterOutlineSection,
)
from edu_exam_agent.ui.pages.generation_pages import PracticeGenerationPage


class _Courses:
    def list(self):
        return [SimpleNamespace(id=1, name="沪科版八年级数学")]


class _Documents:
    def list(self, _course_id):
        return [
            SimpleNamespace(
                id=10,
                filename="沪科版八年级下册数学.pdf",
                parse_status="completed",
            )
        ]

    def chapter_outline(self, _document_id):
        return (
            ChapterOutlineItem(
                "第17章 一元二次方程",
                (101, 102),
                (
                    ChapterOutlineSection("17.1 一元二次方程", 101),
                    ChapterOutlineSection("17.2 一元二次方程的解法", 102),
                ),
            ),
            ChapterOutlineItem(
                "第18章 勾股定理",
                (201, 202),
                (
                    ChapterOutlineSection("18.1 勾股定理", 201),
                    ChapterOutlineSection("18.2 勾股定理的逆定理", 202),
                ),
            ),
            ChapterOutlineItem(
                "第19章 四边形",
                (301,),
                (ChapterOutlineSection("19.1 多边形内角和", 301),),
            ),
        )


class _EmptyService:
    def list(self, *_args, **_kwargs):
        return []


def _page() -> PracticeGenerationPage:
    QApplication.instance() or QApplication([])
    return PracticeGenerationPage(
        _Courses(),
        _Documents(),
        _EmptyService(),
        _EmptyService(),
        None,
        None,
        _EmptyService(),
    )


def _texts(widget) -> list[str]:
    return [widget.item(index).text() for index in range(widget.count())]


def test_chapter_selector_shows_only_major_chapters_and_selected_sections() -> None:
    page = _page()
    page.scope.setCurrentIndex(2)

    assert _texts(page.chapters) == [
        "第17章 一元二次方程",
        "第18章 勾股定理",
        "第19章 四边形",
    ]
    assert page.chapters.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection

    page.chapters.item(1).setSelected(True)
    QApplication.processEvents()

    assert _texts(page.chapter_sections) == [
        "18.1 勾股定理",
        "18.2 勾股定理的逆定理",
    ]
    assert page._selected_chapter_ids() == (201, 202)


def test_cross_chapter_selection_groups_sections_and_collapses_back_to_single() -> None:
    page = _page()
    page.scope.setCurrentIndex(3)
    page.chapters.item(0).setSelected(True)
    page.chapters.item(1).setSelected(True)
    QApplication.processEvents()

    assert page.chapters.selectionMode() == QAbstractItemView.SelectionMode.MultiSelection
    assert page._selected_chapter_ids() == (101, 102, 201, 202)
    section_texts = _texts(page.chapter_sections)
    assert "第17章 一元二次方程" in section_texts
    assert "第18章 勾股定理" in section_texts
    assert "18.2 勾股定理的逆定理" in section_texts

    page.scope.setCurrentIndex(2)
    QApplication.processEvents()

    assert page.chapters.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert len(page.chapters.selectedItems()) <= 1
    assert len(page._selected_chapter_ids()) <= 2


@pytest.mark.parametrize(
    ("width", "height", "expects_scroll"),
    ((1544, 1261, False), (1280, 720, True), (1024, 768, True)),
)
def test_generation_page_keeps_form_controls_intact_when_resized(
    width: int, height: int, expects_scroll: bool
) -> None:
    page = _page()
    page.resize(width, height)
    page.show()
    QApplication.processEvents()

    controls = (
        page.course,
        page.scope,
        page.document,
        page.chapter_button,
        page.title_input,
        page.count,
        page.minimum,
        page.difficulty,
        page.duration,
        *page.type_count_spins.values(),
    )
    assert all(control.height() == 40 for control in controls)

    document_item = page.document.parentWidget()
    title_item = page.title_input.parentWidget()
    document_bottom = document_item.mapTo(
        page.scroll_content, document_item.rect().bottomLeft()
    ).y()
    title_top = title_item.mapTo(page.scroll_content, title_item.rect().topLeft()).y()
    assert document_bottom < title_top
    if expects_scroll:
        assert page.page_scroll.verticalScrollBar().maximum() > 0
    page.close()


def test_chapter_button_opens_popup_inside_screen_and_updates_summary() -> None:
    page = _page()
    page.resize(1024, 768)
    page.show()
    page.scope.setCurrentIndex(2)
    QApplication.processEvents()

    assert page.chapter_button.text() == "请选择章节"
    page.chapter_button.click()
    QApplication.processEvents()

    assert page.chapter_popup.isVisible()
    assert page.chapter_popup.windowFlags() & Qt.WindowType.Popup
    screen_rect = page.chapter_button.screen().availableGeometry()
    assert screen_rect.contains(page.chapter_popup.frameGeometry())
    assert _texts(page.chapters) == [
        "第17章 一元二次方程",
        "第18章 勾股定理",
        "第19章 四边形",
    ]

    page.chapters.item(1).setSelected(True)
    QApplication.processEvents()
    assert page.chapter_button.text() == "第18章 勾股定理"
    assert _texts(page.chapter_sections) == [
        "18.1 勾股定理",
        "18.2 勾股定理的逆定理",
    ]

    page.chapter_popup.hide()
    page.resize(1280, 720)
    QApplication.processEvents()
    page.chapter_button.click()
    QApplication.processEvents()
    assert screen_rect.contains(page.chapter_popup.frameGeometry())
    page.close()


def test_scope_without_chapters_closes_popup_and_resets_button() -> None:
    page = _page()
    page.show()
    page.scope.setCurrentIndex(3)
    page.chapters.item(0).setSelected(True)
    page.chapters.item(1).setSelected(True)
    page.chapter_button.click()
    QApplication.processEvents()

    assert page.chapter_button.text() == "已选择 2 个章节"
    assert page.chapter_popup.isVisible()

    page.scope.setCurrentIndex(1)
    QApplication.processEvents()
    assert not page.chapter_popup.isVisible()
    assert not page.chapter_button.isEnabled()
    assert page.chapter_button.text() == "无需选择章节"
    assert page._selected_chapter_ids() == ()
    page.close()


def test_generation_spin_boxes_hide_buttons_and_keep_keyboard_controls() -> None:
    page = _page()
    page.show()
    QApplication.processEvents()

    spin_boxes = (
        page.count,
        page.minimum,
        page.duration,
        *page.type_count_spins.values(),
    )
    assert all(
        spin_box.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        for spin_box in spin_boxes
    )
    assert all(spin_box.height() == 40 for spin_box in spin_boxes)
    assert all(
        spin_box.alignment()
        == (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for spin_box in spin_boxes
    )

    choice_count = page.type_count_spins["单项选择题"]
    original_total = page.count.value()
    original_choice_count = choice_count.value()
    choice_count.setFocus()
    QTest.keyClick(choice_count, Qt.Key.Key_Up)
    assert choice_count.value() == original_choice_count + 1
    assert page.count.value() == original_total + 1
    QTest.keyClick(choice_count, Qt.Key.Key_Down)
    assert choice_count.value() == original_choice_count
    assert page.count.value() == original_total

    page.minimum.setValue(-100)
    page.duration.setValue(1000)
    assert page.minimum.value() == page.minimum.minimum() == 0
    assert page.duration.value() == page.duration.maximum() == 300
    page.close()


def test_type_counts_drive_read_only_total_and_zero_blocks_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page()
    assert page.count.isReadOnly()
    assert page.count.value() == sum(
        spin.value() for spin in page.type_count_spins.values()
    )

    for spin in page.type_count_spins.values():
        spin.setValue(0)
    assert page.count.value() == 0
    assert page._type_counts() == ()

    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message: messages.append(message),
    )
    page.generate()
    assert messages == ["请至少将一种题型数量设为1。"]
    page.close()
