"""Text cleaning, chapter recognition and bounded chunk creation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from edu_exam_agent.infrastructure.parsers import ParsedDocument

_CHAPTER_PATTERNS = (
    re.compile(r"^第[一二三四五六七八九十百零〇0-9]+[章节单元篇]\s*.*$"),
    re.compile(r"^\d+(?:\.\d+){1,3}\s+\S.*$"),
)

_MAJOR_CHAPTER = re.compile(r"^第\s*([一二三四五六七八九十百零〇0-9]+)\s*章[\s　]*(.*)$")
_NUMBERED_SECTION = re.compile(r"^(\d+)\.(\d+)\s+(.+)$")
_TOC_NON_SECTION_PREFIXES = (
    "目录",
    "数学拓展",
    "数学史话",
    "数学活动",
    "信息技术应用",
    "阅读与思考",
    "阅读与欣赏",
    "综合与实践",
    "小结",
    "复习题",
    "附录",
    "后记",
)


@dataclass(frozen=True, slots=True)
class ChapterSection:
    title: str
    page_start: int
    page_end: int
    content: str


@dataclass(frozen=True, slots=True)
class TocChapter:
    number: str
    title: str
    sections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextChunk:
    chapter_title: str
    page_start: int
    page_end: int
    content: str
    character_count: int


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\d)[\ue000-\uf8ff]\s*(?=\d)", ".", text)
    text = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text)
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
    if _MAJOR_CHAPTER.match(candidate):
        return True
    section = _NUMBERED_SECTION.match(candidate)
    if section is None:
        return False
    title = section.group(3).strip()
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", title))
    return (
        2 <= chinese_count
        and len(title) <= 36
        and not re.search(r"[，。！？：；,!?;=（）()]", title)
    )


def _compact_title(value: str) -> str:
    value = re.sub(r"[\s　]+", " ", value).strip()
    value = re.split(r"(?:[.!…]{2,}|\s+\d+\s*(?:[.!…]+|$))", value, maxsplit=1)[0]
    return value.strip(" .!…·")


def _heading_key(value: str) -> tuple[str, str] | None:
    compact = re.sub(r"\s+", "", value)
    major = _MAJOR_CHAPTER.match(compact)
    if major:
        return "major", major.group(1)
    section = _NUMBERED_SECTION.match(value)
    if section:
        return "section", f"{section.group(1)}.{section.group(2)}"
    return None


def recognize_table_of_contents(document: ParsedDocument) -> list[TocChapter]:
    """Read the printed contents pages as the authority for chapter and section names."""
    chapters: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    pending_major_title = ""
    in_toc = False
    toc_pages_seen = 0
    for page in document.pages[:20]:
        text = clean_text(page.text)
        if any(
            re.fullmatch(r"目\s*录", line.strip()) for line in text.splitlines()
        ):
            in_toc = True
        if not in_toc:
            continue
        toc_pages_seen += 1
        toc_lines = text.splitlines()
        section_line_count = sum(
            _NUMBERED_SECTION.match(line.strip()) is not None for line in toc_lines
        )
        if (
            toc_pages_seen >= 2
            and section_line_count >= 2
            and "…" not in text
            and not re.search(r"\.{3,}", text)
        ):
            break
        if toc_pages_seen >= 2 and re.search(
            r"(?m)^\s*\d+\s+(?:第\s*\d+\s*章|\d+\.\d+\s+)", text
        ):
            break
        for raw_line in text.splitlines():
            line = _compact_title(raw_line)
            major = _MAJOR_CHAPTER.match(line)
            if major:
                number = major.group(1)
                if current is not None and (
                    number == current[0] or any(number == item[0] for item in chapters)
                ):
                    chapters.append(current)
                    return [
                        TocChapter(item_number, title, tuple(sections))
                        for item_number, title, sections in chapters
                    ]
                if current is not None:
                    chapters.append(current)
                title_text = _compact_title(major.group(2))
                current = (number, f"第{number}章 {title_text}".strip(), [])
                pending_major_title = ""
                continue
            generic_major = re.match(r"^\u7b2c\s*\u7ae0[\s\u3000]*(.*)$", line)
            if generic_major:
                if current is not None:
                    chapters.append(current)
                    current = None
                pending_major_title = _compact_title(generic_major.group(1))
                continue
            section = _NUMBERED_SECTION.match(line)
            if current is None and pending_major_title and section is not None:
                number = section.group(1)
                current = (number, f"第{number}章 {pending_major_title}".strip(), [])
                pending_major_title = ""
            if current is None or not re.search(r"[\u4e00-\u9fff]", line):
                continue
            chinese_start = re.search(r"[\u4e00-\u9fff]", line)
            if chinese_start is None:
                continue
            prefix = line[: chinese_start.start()].strip()
            if not prefix:
                continue
            candidate = line[chinese_start.start() :]
            candidate = re.sub(r"[^\u4e00-\u9fff、]+$", "", candidate).strip()
            if not candidate or candidate.startswith(_TOC_NON_SECTION_PREFIXES):
                continue
            if len(candidate) > 32:
                continue
            current[2].append(candidate)
        if toc_pages_seen >= 4 and current is not None:
            break
    if current is not None:
        chapters.append(current)
    return [TocChapter(number, title, tuple(sections)) for number, title, sections in chapters]


def recognize_chapters(document: ParsedDocument) -> list[ChapterSection]:
    chapters: list[ChapterSection] = []
    toc = recognize_table_of_contents(document)
    has_toc_pages = any(
        any(
            re.fullmatch(r"目\s*录", line.strip())
            for line in clean_text(page.text).splitlines()
        )
        for page in document.pages[:20]
    )
    toc_started = False
    body_started = not has_toc_pages
    first_toc_number = toc[0].number if toc else ""
    current_title = "未分章内容"
    current_page = 1
    last_content_page = 1
    buffer: list[str] = []
    allow_markdown = document.source_format in {".md", ".markdown"}

    def flush() -> None:
        content = clean_text("\n".join(buffer))
        if content or (_heading_key(current_title) or (None,))[0] == "major":
            chapters.append(ChapterSection(current_title, current_page, last_content_page, content))

    for page in document.pages:
        lines = clean_text(page.text).splitlines()
        if has_toc_pages and any(
            re.fullmatch(r"目\s*录", line.strip()) for line in lines
        ):
            toc_started = True
            continue
        if toc_started and not body_started:
            if first_toc_number:
                body_started = any(
                    re.match(
                        rf"^第\s*{re.escape(first_toc_number)}\s*章", line.strip()
                    )
                    or re.match(
                        rf"^{re.escape(first_toc_number)}\.1(?:\s|$)", line.strip()
                    )
                    for line in lines
                )
            else:
                body_started = any(_MAJOR_CHAPTER.match(line.strip()) for line in lines)
            if not body_started:
                continue
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
                new_title = re.sub(r"^#{1,6}\s+", "", line).strip()
                new_key = _heading_key(new_title)
                current_key = _heading_key(current_title)
                same_heading = new_key is not None and new_key == current_key
                repeated_major_header = (
                    new_key is not None
                    and current_key is not None
                    and new_key[0] == "major"
                    and current_key[0] == "section"
                    and new_key[1] == current_key[1].split(".", 1)[0]
                )
                if same_heading or repeated_major_header:
                    index += 1
                    continue
                flush()
                buffer.clear()
                current_title = new_title
                current_page = page.page_number
            else:
                buffer.append(line)
                last_content_page = page.page_number
            index += 1
    flush()

    deduplicated: dict[tuple[str, str], tuple[int, ChapterSection]] = {}
    unkeyed: list[tuple[int, ChapterSection]] = []
    for order, chapter in enumerate(chapters):
        key = _heading_key(chapter.title)
        if key is None:
            unkeyed.append((order, chapter))
            continue
        previous = deduplicated.get(key)
        if previous is None or len(chapter.content) > len(previous[1].content):
            deduplicated[key] = (order, chapter)
    chapters = [
        chapter
        for _, chapter in sorted(
            (*unkeyed, *deduplicated.values()), key=lambda item: item[0]
        )
    ]

    numbered = [chapter for chapter in chapters if _NUMBERED_SECTION.match(chapter.title)]
    if not toc or not numbered:
        return chapters

    body_by_major: dict[str, list[ChapterSection]] = {}
    body_major_rows: dict[str, ChapterSection] = {}
    for chapter in chapters:
        section_match = _NUMBERED_SECTION.match(chapter.title)
        if section_match:
            body_by_major.setdefault(section_match.group(1), []).append(chapter)
            continue
        major_match = _MAJOR_CHAPTER.match(chapter.title)
        if major_match:
            body_major_rows[major_match.group(1)] = chapter

    rebuilt: list[ChapterSection] = []
    for toc_chapter in toc:
        body_sections = body_by_major.get(toc_chapter.number, [])
        if not body_sections:
            continue
        major_source = body_major_rows.get(toc_chapter.number)
        rebuilt.append(
            ChapterSection(
                toc_chapter.title,
                major_source.page_start if major_source else body_sections[0].page_start,
                body_sections[-1].page_end,
                major_source.content if major_source else "",
            )
        )
        for index, body_section in enumerate(body_sections, 1):
            body_match = _NUMBERED_SECTION.match(body_section.title)
            raw_name = (
                toc_chapter.sections[index - 1]
                if index <= len(toc_chapter.sections)
                else body_match.group(3)
            )
            section_name = re.sub(
                r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])",
                "",
                raw_name,
            )
            rebuilt.append(
                ChapterSection(
                    f"{toc_chapter.number}.{index} {section_name}",
                    body_section.page_start,
                    body_section.page_end,
                    body_section.content,
                )
            )
    return rebuilt or chapters


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
