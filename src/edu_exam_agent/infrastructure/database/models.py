"""Initial database metadata used to track schema initialization."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    """Minimal schema marker; migrations replace this mechanism in phase two."""

    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class CourseModel(Base):
    """Persisted teacher course configuration."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    education_stage: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    grade: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    semester: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    textbook_version: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    default_total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    default_difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentModel(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("course_id", "file_hash", name="uq_document_course_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    parse_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chapter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class ChapterModel(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DocumentChunkModel(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)


class LLMProviderConfigModel(Base):
    __tablename__ = "llm_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LLMProviderAuditModel(Base):
    __tablename__ = "llm_provider_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class KnowledgePointModel(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (
        UniqueConstraint("course_id", "chapter_id", "name", name="uq_kp_chapter_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="automatic")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="candidate")
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    recommended_difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    recommended_question_types: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    teacher_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class QuestionModel(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    question_type: Mapped[str] = mapped_column(String(100), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    analysis: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    knowledge_points_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    recommendation_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    boundary_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    generation_model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class QuestionSourceModel(Base):
    __tablename__ = "question_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), nullable=False
    )
    evidence: Mapped[str] = mapped_column(Text, nullable=False)


class QuestionFigureModel(Base):
    __tablename__ = "question_figures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    svg_text: Mapped[str] = mapped_column(Text, nullable=False)
    png_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class QuestionValidationModel(Base):
    __tablename__ = "question_validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quality_score: Mapped[float] = mapped_column(nullable=False)
    issues_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class QuestionScoreDetailModel(Base):
    __tablename__ = "question_score_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    total_points: Mapped[float] = mapped_column(nullable=False)
    dimensions_json: Mapped[str] = mapped_column(Text, nullable=False)
    calculation_load: Mapped[int] = mapped_column(Integer, nullable=False)
    fusion_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    hard_point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    notes_json: Mapped[str] = mapped_column(Text, nullable=False)


class QuestionVersionModel(Base):
    __tablename__ = "question_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(30), nullable=False, default="teacher")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
