from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class EvalCase(Base):
    __tablename__ = "eval_cases"
    __table_args__ = (
        CheckConstraint("case_type in ('rag', 'sql', 'hybrid', 'safety')", name="ck_eval_cases_case_type"),
        CheckConstraint(
            "expected_route_type is null or expected_route_type in ('POLICY_QA', 'DATA_QA', 'HYBRID_QA', 'OTHER')",
            name="ck_eval_cases_expected_route_type",
        ),
        UniqueConstraint("case_type", "question", name="uq_eval_cases_case_type_question"),
        Index("ix_eval_cases_case_type_enabled", "case_type", "enabled"),
        Index("ix_eval_cases_expected_route_type", "expected_route_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_route_type: Mapped[str | None] = mapped_column(String(32))
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    expected_sources_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expected_view: Mapped[str | None] = mapped_column(String(128))
    expected_metric_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expected_sql_pattern: Mapped[str | None] = mapped_column(Text)
    expected_sql_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expected_keywords_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    judge_model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'running', 'success', 'failed')", name="ck_eval_runs_status"),
        Index("ix_eval_runs_status_started", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    judge_model: Mapped[str | None] = mapped_column(String(128))
    prompt_versions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    run_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EvalResult(Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        CheckConstraint("retrieval_score is null or retrieval_score >= 0", name="ck_eval_results_retrieval_score"),
        CheckConstraint("citation_score is null or citation_score >= 0", name="ck_eval_results_citation_score"),
        CheckConstraint(
            "groundedness_score is null or groundedness_score >= 0",
            name="ck_eval_results_groundedness_score",
        ),
        Index("ix_eval_results_eval_run_id", "eval_run_id"),
        Index("ix_eval_results_trace_id", "trace_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    eval_run_id: Mapped[UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False)
    eval_case_id: Mapped[UUID] = mapped_column(ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False)
    trace_id: Mapped[UUID | None] = mapped_column(ForeignKey("qa_traces.id", ondelete="SET NULL"))
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retrieval_score: Mapped[float | None] = mapped_column(Float)
    sql_valid: Mapped[bool | None] = mapped_column(Boolean)
    citation_score: Mapped[float | None] = mapped_column(Float)
    groundedness_score: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
