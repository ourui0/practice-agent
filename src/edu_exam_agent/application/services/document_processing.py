"""Text cleaning, chapter recognition and bounded chunk creation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from edu_exam_agent.infrastructure.parsers import ParsedDocument

_CHAPTER_PATTERNS = (
    re.compile(r"^第[一二三四五六七八九十百零〇0-9]+[章节单元篇]\s*.*$"),
    re.compile(r"^\d+(?:\.\d+){1,3}\s+\S.*$"),
)


@dataclass(frozen=True, slots=True)
class ChapterSection:
    title: str
    page_start: int
    page_end: int
    content: str


@dataclass(frozen=True, slots=True)
class TextChunk:
    chapter_title: str
    page_start: int
    page_end: int
    content: str
    character_count: int


def clean_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "").split("\n")]
    output: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if output and not blank:
                output.append("")
            blank = True
        else:
            output.append(line)
            blank = False
    return "\n".join(output).strip()


def is_chapter_heading(line: str, allow_markdown: bool = False) -> bool:
    candidate = line.strip()
    if not candidate or len(candidate) > 80:
        return False
    if allow_markdown and re.match(r"^#{1,6}\s+[\w\u4e00-\u9fff].*$", candidate):
        return True
    return any(pattern.match(candidate) for pattern in _CHAPTER_PATTERNS)


def recognize_chapters(document: ParsedDocument) -> list[ChapterSection]:
    chapters: list[ChapterSection] = []
    current_title = "未分章内容"
    current_page = 1
    last_content_page = 1
    buffer: list[str] = []
    allow_markdown = document.source_format in {".md", ".markdown"}

    def flush() -> None:
        content = clean_text("\n".join(buffer))
        if content:
            chapters.append(ChapterSection(current_title, current_page, last_content_page, content))

    for page in document.pages:
        lines = clean_text(page.text).splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if re.fullmatch(r"\d+\.\d+", line) and index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                chinese_count = len(re.findall(r"[\u4e00-\u9fff]", next_line))
                if 2 <= chinese_count and len(next_line) <= 50:
                    line = f"{line} {next_line}"
                    index += 1
            if is_chapter_heading(line, allow_markdown=allow_markdown):
                flush()
                buffer.clear()
                current_title = re.sub(r"^#{1,6}\s+", "", line).strip()
                current_page = page.page_number
            else:
                buffer.append(line)
                last_content_page = page.page_number
            index += 1
    flush()
    return chapters


def create_chunks(chapters: list[ChapterSection], max_chars: int = 1200) -> list[TextChunk]:
    if max_chars < 100:
        raise ValueError("文本块长度不能小于 100 个字符")
    chunks: list[TextChunk] = []
    for chapter in chapters:
        paragraphs = [
            item.strip() for item in re.split(r"\n\s*\n", chapter.content) if item.strip()
        ]
        buffer = ""
        for paragraph in paragraphs:
            for candidate in (
                paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)
            ):
                if buffer and len(buffer) + len(candidate) + 2 > max_chars:
                    chunks.append(
                        TextChunk(
                            chapter.title,
                            chapter.page_end,
                            chapter.page_start,
                            buffer,
                            len(buffer),
                        )
                    )
                    buffer = ""
                buffer = f"{buffer}\n\n{candidate}".strip()
        if buffer:
            chunks.append(
                TextChunk(chapter.title, chapter.page_start, chapter.page_end, buffer, len(buffer))
            )
    return chunks
