"""Re-render persisted figures after renderer improvements."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_exam_agent.app.bootstrap import bootstrap
from edu_exam_agent.domain.schemas import QuestionDiagram
from edu_exam_agent.infrastructure.database.models import QuestionFigureModel
from edu_exam_agent.infrastructure.rendering import render_diagram


def main() -> None:
    context = bootstrap()
    updated = 0
    with Session(context.engine) as session, session.begin():
        for figure in session.scalars(select(QuestionFigureModel)):
            diagram = QuestionDiagram.model_validate_json(figure.spec_json)
            figure.svg_text, figure.png_data = render_diagram(diagram)
            updated += 1
    print(f"已重新渲染 {updated} 张题目配图")


if __name__ == "__main__":
    main()
