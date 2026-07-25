"""Knowledge-point candidates and teacher confirmation workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from edu_exam_agent.infrastructure.database.models import (
    ChapterModel,
    DocumentModel,
    KnowledgePointModel,
)


@dataclass(frozen=True, slots=True)
class KnowledgePointInput:
    name: str
    description: str = ""
    importance: int = 3
    recommended_difficulty: int = 3
    recommended_question_types: str = "选择题、填空题"
    teacher_note: str = ""
    is_enabled: bool = True

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("知识点名称不能为空")
        if self.importance not in range(1, 6):
            raise ValueError("重要程度必须在 1 到 5 之间")
        if self.recommended_difficulty not in range(1, 6):
            raise ValueError("推荐难度必须在 1 到 5 之间")


class KnowledgePointService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list(self, course_id: int) -> list[KnowledgePointModel]:
        with Session(self._engine) as session:
            statement = (
                select(KnowledgePointModel)
                .where(KnowledgePointModel.course_id == course_id)
                .order_by(KnowledgePointModel.status, KnowledgePointModel.id)
            )
            return list(session.scalars(statement))

    def extract_candidates(self, course_id: int) -> int:
        with Session(self._engine) as session:
            self._remove_invalid_automatic_points(session, course_id)
            chapters = list(
                session.scalars(
                    select(ChapterModel)
                    .join(DocumentModel, DocumentModel.id == ChapterModel.document_id)
                    .where(
                        DocumentModel.course_id == course_id,
                        ChapterModel.is_excluded.is_(False),
                    )
                    .order_by(ChapterModel.position)
                )
            )
            existing = {
                (item.chapter_id, item.name)
                for item in session.scalars(
                    select(KnowledgePointModel).where(KnowledgePointModel.course_id == course_id)
                )
            }
            created = 0
            for chapter in chapters:
                name = self._knowledge_name(chapter.title)
                if not name or (chapter.id, name) in existing:
                    continue
                session.add(
                    KnowledgePointModel(
                        course_id=course_id,
                        chapter_id=chapter.id,
                        name=name,
                        description=f"来源章节：{chapter.title}",
                        source="automatic",
                        status="confirmed",
                        source_page=chapter.page_start,
                    )
                )
                created += 1
            session.commit()
            return created

    def confirm_all_candidates(self, course_id: int) -> int:
        with Session(self._engine) as session:
            points = list(
                session.scalars(
                    select(KnowledgePointModel).where(
                        KnowledgePointModel.course_id == course_id,
                        KnowledgePointModel.status == "candidate",
                        KnowledgePointModel.is_enabled.is_(True),
                    )
                )
            )
            for point in points:
                point.status = "confirmed"
            session.commit()
            return len(points)

    @staticmethod
    def _knowledge_name(title: str) -> str:
        value = title.strip(" \t、，。．·")
        if not value or value == "未分章内容":
            return ""
        # Chapter-level table-of-contents labels are containers, not knowledge points.
        if re.match(r"^第\s*[一二三四五六七八九十百零〇两\d]+\s*章(?:\s|$)", value):
            return ""
        value = re.sub(r"^\d+(?:\.\d+)+\s*", "", value).strip(" 、，。．·")
        if re.fullmatch(r"第?\s*[一二三四五六七八九十百零〇两\d]+\s*[章节]", value):
            return ""
        return value

    @classmethod
    def _remove_invalid_automatic_points(cls, session: Session, course_id: int) -> int:
        points = list(
            session.scalars(
                select(KnowledgePointModel).where(
                    KnowledgePointModel.course_id == course_id,
                    KnowledgePointModel.source == "automatic",
                )
            )
        )
        invalid = [point for point in points if not cls._knowledge_name(point.name)]
        for point in invalid:
            session.delete(point)
        return len(invalid)

    def create_manual(self, course_id: int, value: KnowledgePointInput) -> None:
        value.validate()
        with Session(self._engine) as session:
            session.add(
                KnowledgePointModel(
                    course_id=course_id,
                    name=value.name.strip(),
                    description=value.description,
                    source="manual",
                    status="confirmed",
                    importance=value.importance,
                    recommended_difficulty=value.recommended_difficulty,
                    recommended_question_types=value.recommended_question_types,
                    teacher_note=value.teacher_note,
                    is_enabled=value.is_enabled,
                )
            )
            session.commit()

    def update(self, point_id: int, value: KnowledgePointInput) -> None:
        value.validate()
        with Session(self._engine) as session:
            point = session.get(KnowledgePointModel, point_id)
            if point is None:
                raise ValueError("知识点不存在")
            point.name = value.name.strip()
            point.description = value.description
            point.importance = value.importance
            point.recommended_difficulty = value.recommended_difficulty
            point.recommended_question_types = value.recommended_question_types
            point.teacher_note = value.teacher_note
            point.is_enabled = value.is_enabled
            point.status = "confirmed"
            session.commit()

    def confirm(self, point_id: int) -> None:
        with Session(self._engine) as session:
            point = session.get(KnowledgePointModel, point_id)
            if point is None:
                raise ValueError("知识点不存在")
            point.status = "confirmed"
            session.commit()

    def delete(self, point_id: int) -> None:
        with Session(self._engine) as session:
            point = session.get(KnowledgePointModel, point_id)
            if point:
                session.delete(point)
                session.commit()
