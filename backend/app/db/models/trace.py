from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QaTrace(Base):
    __tablename__ = "qa_traces"
    __table_args__ = (
        CheckConstraint(
            "route_type is null or route_type in ('POLICY_QA', 'DATA_QA', 'HYBRID_QA', 'OTHER')",
            name="ck_qa_traces_route_type",
        ),
        CheckConstraint(
            "status in ('running', 'success', 'failed', 'refused')",
            name="ck_qa_traces_status",
        ),
        CheckConstraint("latency_ms is null or latency_ms >= 0", name="ck_qa_traces_latency"),
        Index("ix_qa_traces_user_created", "user_id", "created_at"),
        Index("ix_qa_traces_route_type", "route_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    user_question: Mapped[str] = mapped_column(Text, nullable=False)
    route_type: Mapped[str | None] = mapped_column(String(32))
    final_answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    latency_ms: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class QaTraceSpan(Base):
    __tablename__ = "qa_trace_spans"
    __table_args__ = (
        CheckConstraint("span_order >= 1", name="ck_qa_trace_spans_order"),
        CheckConstraint("latency_ms >= 0", name="ck_qa_trace_spans_latency"),
        CheckConstraint("status in ('success', 'failed', 'skipped')", name="ck_qa_trace_spans_status"),
        CheckConstraint("retry_count >= 0", name="ck_qa_trace_spans_retry_count"),
        UniqueConstraint("trace_id", "span_order", name="uq_qa_trace_spans_trace_order"),
        Index("ix_qa_trace_spans_trace_created", "trace_id", "created_at"),
        Index("ix_qa_trace_spans_span_type", "span_type"),
        Index("ix_qa_trace_spans_parent_span_id", "parent_span_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    trace_id: Mapped[UUID] = mapped_column(ForeignKey("qa_traces.id", ondelete="CASCADE"), nullable=False)
    parent_span_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("qa_trace_spans.id", ondelete="SET NULL")
    )
    span_order: Mapped[int] = mapped_column(nullable=False)
    span_type: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str | None] = mapped_column(String(128))
    prompt_name: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    token_usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
