from __future__ import annotations

from edu_exam_agent.domain.schemas import QuestionDiagram
from edu_exam_agent.infrastructure.rendering import render_diagram


def test_render_diagram_creates_safe_svg_and_png() -> None:
    diagram = QuestionDiagram.model_validate(
        {
            "kind": "geometry",
            "points": [
                {"label": "A", "x": 0, "y": 0},
                {"label": "B", "x": 4, "y": 0},
                {"label": "C", "x": 2, "y": 3},
            ],
            "segments": [
                {"start": "A", "end": "B"},
                {"start": "B", "end": "C"},
                {"start": "C", "end": "A"},
            ],
        }
    )
    svg, png = render_diagram(diagram)
    assert svg.startswith("<svg")
    assert "<line" in svg
    assert png.startswith(b"\x89PNG")
    assert len(png) > 1000


def test_coordinate_diagram_has_origin_named_axes_arrows_and_ticks() -> None:
    diagram = QuestionDiagram.model_validate(
        {
            "kind": "coordinate",
            "points": [
                {"label": "P", "x": 3, "y": -2},
                {"label": "P'", "x": -3, "y": -2},
            ],
            "segments": [],
            "show_axes": True,
        }
    )
    svg, png = render_diagram(diagram)
    assert 'marker-end="url(#axis-arrow)"' in svg
    assert ">x</text>" in svg
    assert ">y</text>" in svg
    assert ">O</text>" in svg
    assert ">-2</text>" in svg
    assert 'y1="210.0"' in svg
    assert 'x1="320.0"' in svg
    assert png.startswith(b"\x89PNG")
