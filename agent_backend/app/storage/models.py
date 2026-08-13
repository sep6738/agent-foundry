"""SQLAlchemy ORM models matching the design report's data model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(64), primary_key=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(128), default="")
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    sessions: Mapped[list[Session]] = relationship(back_populates="user")
    projects: Mapped[list[Project]] = relationship(back_populates="user")
    memory_facts: Mapped[list[MemoryFact]] = relationship(back_populates="user")


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    path: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")

    user: Mapped[User] = relationship(back_populates="projects")
    sessions: Mapped[list[Session]] = relationship(back_populates="project")


class Session(IdMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256), default="Untitled")
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    project: Mapped[Project | None] = relationship(back_populates="sessions")
    entries: Mapped[list[SessionEntry]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    summaries: Mapped[list[SessionSummary]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship(back_populates="session")
    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="session")


class SessionEntry(IdMixin, Base):
    __tablename__ = "session_entries"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    session: Mapped[Session] = relationship(back_populates="entries")


class SessionSummary(IdMixin, TimestampMixin, Base):
    __tablename__ = "session_summaries"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_updated_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    session: Mapped[Session] = relationship(back_populates="summaries")


class MemoryFact(IdMixin, TimestampMixin, Base):
    __tablename__ = "memory_facts"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="fact")
    subject: Mapped[str] = mapped_column(String(256), index=True)
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    scope: Mapped[str] = mapped_column(String(32), default="user")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    status: Mapped[str] = mapped_column(String(32), default="active")
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ttl: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_access_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    user: Mapped[User] = relationship(back_populates="memory_facts")

    __table_args__ = (
        Index("ix_memory_facts_user_kind", "user_id", "kind"),
        Index("ix_memory_facts_scope", "scope"),
    )


class MemoryFactVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "memory_fact_versions"

    fact_id: Mapped[str] = mapped_column(ForeignKey("memory_facts.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("fact_id", "version", name="uq_fact_version"),)


class Event(IdMixin, Base):
    __tablename__ = "events"

    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("sessions.id"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    session: Mapped[Session | None] = relationship(back_populates="events")


class ToolCall(IdMixin, Base):
    __tablename__ = "tool_calls"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped[Session] = relationship(back_populates="tool_calls")


class CompressionRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "compression_records"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    levels_used: Mapped[list[int]] = mapped_column(JSON, default=list)
    tokens_before: Mapped[int] = mapped_column(Integer, default=0)
    tokens_after: Mapped[int] = mapped_column(Integer, default=0)
    summary_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    removed_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    replaced_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    kept_window_entries: Mapped[int] = mapped_column(Integer, default=0)
    cache_invalidated: Mapped[bool] = mapped_column(Integer, default=0)


class GraphCheckpoint(IdMixin, Base):
    """Serialized LangGraph checkpoints for durable resume/interrupt support."""

    __tablename__ = "graph_checkpoints"

    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(128), index=True)
    parent_checkpoint_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    metadata_type: Mapped[str] = mapped_column(String(32))
    metadata_blob: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            name="uq_graph_checkpoint",
        ),
    )


class GraphCheckpointWrite(IdMixin, Base):
    """Pending writes attached to a LangGraph checkpoint."""

    __tablename__ = "graph_checkpoint_writes"

    thread_id: Mapped[str] = mapped_column(String(128), index=True)
    checkpoint_ns: Mapped[str] = mapped_column(String(128), default="")
    checkpoint_id: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str] = mapped_column(String(128))
    idx: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[bytes] = mapped_column(LargeBinary)
    task_path: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
            "task_id",
            "idx",
            name="uq_graph_checkpoint_write",
        ),
    )


class Skill(IdMixin, TimestampMixin, Base):
    __tablename__ = "skills"

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source_path: Mapped[str] = mapped_column(String(512), default="")
    scope: Mapped[str] = mapped_column(String(32), default="project")
    status: Mapped[str] = mapped_column(String(32), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)

    versions: Mapped[list[SkillVersion]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class SkillVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "skill_versions"

    skill_id: Mapped[str] = mapped_column(ForeignKey("skills.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text)

    skill: Mapped[Skill] = relationship(back_populates="versions")


class SkillInvocation(IdMixin, TimestampMixin, Base):
    __tablename__ = "skill_invocations"

    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    skill_id: Mapped[str | None] = mapped_column(ForeignKey("skills.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="auto")
    result: Mapped[str] = mapped_column(String(32), default="ok")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
