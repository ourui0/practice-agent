"""Render a constrained diagram specification to SVG and PNG."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from edu_exam_agent.domain.schemas import QuestionDiagram

_APP = None


def render_diagram(
    diagram: QuestionDiagram, width: int = 640, height: int = 420
) -> tuple[str, bytes]:
    points = {point.label: point for point in diagram.points}
    for segment in diagram.segments:
        if segment.start not in points or segment.end not in points:
            raise ValueError("配图线段引用了不存在的点")
    xs = [point.x for point in diagram.points]
    ys = [point.y for point in diagram.points]
    if diagram.show_axes:
        xs.append(0)
        ys.append(0)
        x_extent = max(max(abs(value) for value in xs), 1) + 1
        y_extent = max(max(abs(value) for value in ys), 1) + 1
        xmin, xmax = -x_extent, x_extent
        ymin, ymax = -y_extent, y_extent
    else:
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
    span_x = max(xmax - xmin, 1)
    span_y = max(ymax - ymin, 1)
    pad = 55

    def project(x_value: float, y_value: float) -> tuple[float, float]:
        x = pad + (x_value - xmin) / span_x * (width - 2 * pad)
        y = height - pad - (y_value - ymin) / span_y * (height - 2 * pad)
        return x, y

    def pos(label: str) -> tuple[float, float]:
        point = points[label]
        return project(point.x, point.y)

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            '<defs><marker id="axis-arrow" markerWidth="8" markerHeight="8" refX="7" '
            'refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#475569"/>'
            "</marker></defs>"
        ),
    ]
    if diagram.show_axes:
        origin_x, origin_y = project(0, 0)
        parts.extend(
            (
                (
                    f'<line x1="{pad}" y1="{origin_y:.1f}" x2="{width-pad}" '
                    f'y2="{origin_y:.1f}" stroke="#475569" stroke-width="1.6" '
                    'marker-end="url(#axis-arrow)"/>'
                ),
                (
                    f'<line x1="{origin_x:.1f}" y1="{height-pad}" x2="{origin_x:.1f}" '
                    f'y2="{pad}" stroke="#475569" stroke-width="1.6" '
                    'marker-end="url(#axis-arrow)"/>'
                ),
                (
                    f'<text x="{width-pad+8}" y="{origin_y+5:.1f}" '
                    'font-family="Arial" font-size="18" font-style="italic">x</text>'
                ),
                (
                    f'<text x="{origin_x+8:.1f}" y="{pad-8}" '
                    'font-family="Arial" font-size="18" font-style="italic">y</text>'
                ),
                (
                    f'<text x="{origin_x-18:.1f}" y="{origin_y+20:.1f}" '
                    'font-family="Arial" font-size="15">O</text>'
                ),
            )
        )
        tick_min_x = max(int(xmin), -20)
        tick_max_x = min(int(xmax), 20)
        for tick in range(tick_min_x, tick_max_x + 1):
            if tick == 0:
                continue
            tick_x, _ = project(tick, 0)
            parts.append(
                f'<line x1="{tick_x:.1f}" y1="{origin_y-4:.1f}" x2="{tick_x:.1f}" '
                f'y2="{origin_y+4:.1f}" stroke="#475569"/>'
            )
            parts.append(
                f'<text x="{tick_x-5:.1f}" y="{origin_y+20:.1f}" '
                f'font-family="Arial" font-size="12">{tick}</text>'
            )
        tick_min_y = max(int(ymin), -20)
        tick_max_y = min(int(ymax), 20)
        for tick in range(tick_min_y, tick_max_y + 1):
            if tick == 0:
                continue
            _, tick_y = project(0, tick)
            parts.append(
                f'<line x1="{origin_x-4:.1f}" y1="{tick_y:.1f}" x2="{origin_x+4:.1f}" '
                f'y2="{tick_y:.1f}" stroke="#475569"/>'
            )
            parts.append(
                f'<text x="{origin_x+8:.1f}" y="{tick_y+4:.1f}" '
                f'font-family="Arial" font-size="12">{tick}</text>'
            )
    for segment in diagram.segments:
        x1, y1 = pos(segment.start)
        x2, y2 = pos(segment.end)
        dash = ' stroke-dasharray="8 6"' if segment.dashed else ""
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#172033" stroke-width="2.5"{dash}/>'
        )
    for point in diagram.points:
        x, y = pos(point.label)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#172033"/>')
        parts.append(
            f'<text x="{x+8:.1f}" y="{y-8:.1f}" '
            f'font-family="Microsoft YaHei,Arial" font-size="18" fill="#172033">'
            f"{escape(point.label)}</text>"
        )
    parts.append("</svg>")
    svg = "".join(parts)
    return svg, _to_png(svg, width, height)


def _to_png(svg: str, width: int, height: int) -> bytes:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)
