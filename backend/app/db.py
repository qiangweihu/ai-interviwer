from __future__ import annotations

from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "anonymous_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="needs_onboarding", index=True)
    profile_revision: Mapped[int] = mapped_column(Integer, default=0)
    current_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_interviewer_style_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    profile: Mapped["Profile | None"] = relationship(back_populates="session", cascade="all, delete-orphan", uselist=False)
    runs: Mapped[list["InterviewRun"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    session_id: Mapped[str] = mapped_column(ForeignKey("anonymous_sessions.id", ondelete="CASCADE"), primary_key=True)
    direction: Mapped[str] = mapped_column(Text)
    target_group: Mapped[str] = mapped_column(Text, default="待确认")
    target_program: Mapped[str] = mapped_column(Text, default="待确认")
    research_context_json: Mapped[str] = mapped_column(Text)
    candidate_profile_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    session: Mapped[SessionRecord] = relationship(back_populates="profile")


class InterviewRun(Base):
    __tablename__ = "interview_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("anonymous_sessions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ready_for_planning", index=True)
    profile_revision: Mapped[int] = mapped_column(Integer)
    plan_profile_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    interviewer_style_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    session: Mapped[SessionRecord] = relationship(back_populates="runs")
    # `research_sources` is retained in the ORM solely so existing databases
    # can still be opened and cleaned up. New runs never create source rows;
    # external research was removed from the runtime.
    sources: Mapped[list["ResearchSource"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    turns: Mapped[list["InterviewTurn"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="InterviewTurn.sequence")
    observations: Mapped[list["Observation"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    practical_submissions: Mapped[list["PracticalSubmission"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="PracticalSubmission.created_at")


class ResearchSource(Base):
    """Historical source rows kept for backwards-compatible database cleanup.

    The current planner is intentionally offline and does not read or write
    this table. Keep the mapping until a deliberate data migration removes the
    legacy table from all deployments.
    """

    __tablename__ = "research_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("interview_runs.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    accessed_at: Mapped[str] = mapped_column(String(32))
    conclusion: Mapped[str] = mapped_column(Text)
    relation: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped[InterviewRun] = relationship(back_populates="sources")


class InterviewTurn(Base):
    __tablename__ = "interview_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("interview_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_topic_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn_kind: Mapped[str] = mapped_column(String(32), default="oral")
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[InterviewRun] = relationship(back_populates="turns")


class PracticalSubmission(Base):
    """The immutable final artifact and machine evidence for a practical task.

    Public trial runs are intentionally not stored as source code.  Only the
    final submission is retained for feedback and later review.
    """

    __tablename__ = "practical_submissions"
    __table_args__ = (UniqueConstraint("run_id", "request_id", name="uq_practical_submission_run_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("interview_runs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str] = mapped_column(String(128), index=True)
    turn_sequence: Mapped[int] = mapped_column(Integer)
    task_type: Mapped[str] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str] = mapped_column(Text)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    run: Mapped[InterviewRun] = relationship(back_populates="practical_submissions")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("interview_runs.id", ondelete="CASCADE"), index=True)
    turn_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str] = mapped_column(Text)
    needs_clarification: Mapped[bool] = mapped_column(Boolean, default=False)

    run: Mapped[InterviewRun] = relationship(back_populates="observations")


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def cleanup_expired(db) -> int:
    now = utcnow()
    expired = db.scalars(select(SessionRecord).where(SessionRecord.expires_at < now)).all()
    for item in expired:
        db.delete(item)
    if expired:
        db.commit()
    return len(expired)
