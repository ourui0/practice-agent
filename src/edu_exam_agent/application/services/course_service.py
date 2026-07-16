"""Course use cases and input validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.models import CourseModel


@dataclass(frozen=True, slots=True)
class CourseInput:
    name: str
    subject: str = ""
    education_stage: str = ""
    grade: str = ""
    semester: str = ""
    textbook_version: str = ""
    description: str = ""
    default_duration_minutes: int = 90
    default_total_score: int = 100
    default_difficulty: int = 3

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("课程名称不能为空")
        if self.default_duration_minutes < 1:
            raise ValueError("考试时长必须大于 0")
        if self.default_total_score < 1:
            raise ValueError("默认总分必须大于 0")
        if self.default_difficulty not in range(1, 6):
            raise ValueError("默认难度必须在 1 到 5 之间")


class CourseService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(self, include_archived: bool = False) -> list[CourseModel]:
        with Session(self._engine) as session:
            statement = select(CourseModel)
            if not include_archived:
                statement = statement.where(CourseModel.is_archived.is_(False))
            return list(session.scalars(statement.order_by(CourseModel.updated_at.desc())))

    def create(self, value: CourseInput) -> CourseModel:
        value.validate()
        with Session(self._engine) as session:
            course = CourseModel(**asdict(value))
            session.add(course)
            session.commit()
            session.refresh(course)
            session.expunge(course)
            return course

    def update(self, course_id: int, value: CourseInput) -> None:
        value.validate()
        with Session(self._engine) as session:
            course = session.get(CourseModel, course_id)
            if course is None:
                raise ValueError("课程不存在")
            for field, content in asdict(value).items():
                setattr(course, field, content)
            session.commit()

    def delete(self, course_id: int) -> None:
        with Session(self._engine) as session:
            course = session.get(CourseModel, course_id)
            if course is not None:
                session.delete(course)
                session.commit()

    def set_archived(self, course_id: int, archived: bool) -> None:
        with Session(self._engine) as session:
            course = session.get(CourseModel, course_id)
            if course is None:
                raise ValueError("课程不存在")
            course.is_archived = archived
            session.commit()

    def duplicate(self, course_id: int) -> CourseModel:
        with Session(self._engine) as session:
            source = session.get(CourseModel, course_id)
            if source is None:
                raise ValueError("课程不存在")
            value = CourseInput(
                name=f"{source.name}（副本）",
                subject=source.subject,
                education_stage=source.education_stage,
                grade=source.grade,
                semester=source.semester,
                textbook_version=source.textbook_version,
                description=source.description,
                default_duration_minutes=source.default_duration_minutes,
                default_total_score=source.default_total_score,
                default_difficulty=source.default_difficulty,
            )
        return self.create(value)
