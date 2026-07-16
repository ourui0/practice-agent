from __future__ import annotations

from edu_exam_agent.application.services.course_service import CourseInput, CourseService
from edu_exam_agent.infrastructure.database.engine import (
    create_database_engine,
    initialize_database,
)


def service(tmp_path) -> CourseService:
    engine = create_database_engine(tmp_path / "courses.db")
    initialize_database(engine)
    return CourseService(engine)


def test_course_crud_duplicate_and_archive(tmp_path) -> None:
    courses = service(tmp_path)
    created = courses.create(
        CourseInput(name="八年级物理", subject="物理", default_total_score=100)
    )
    assert [item.name for item in courses.list()] == ["八年级物理"]

    courses.update(
        created.id, CourseInput(name="八年级物理上册", subject="物理", default_total_score=120)
    )
    assert courses.list()[0].default_total_score == 120

    duplicate = courses.duplicate(created.id)
    assert duplicate.name == "八年级物理上册（副本）"
    courses.set_archived(created.id, True)
    assert [item.id for item in courses.list()] == [duplicate.id]
    assert len(courses.list(include_archived=True)) == 2

    courses.delete(duplicate.id)
    assert len(courses.list(include_archived=True)) == 1


def test_course_name_is_required(tmp_path) -> None:
    courses = service(tmp_path)
    try:
        courses.create(CourseInput(name="  "))
    except ValueError as exc:
        assert "课程名称" in str(exc)
    else:
        raise AssertionError("空课程名称应被拒绝")
