from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.trace import QaTrace, QaTraceSpan


class TraceNotFoundError(ValueError):
    pass


class TraceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_trace(self, *, user_id: UUID | None, question: str) -> QaTrace:
        trace = QaTrace(
            user_id=user_id,
            user_question=question,
            status="running",
        )
        self.db.add(trace)
        self.db.flush()
        return trace

    def add_span(
        self,
        *,
        trace_id: UUID,
        span_type: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any] | None,
        latency_ms: int,
        status: str,
        parent_span_id: UUID | None = None,
        span_order: int | None = None,
        model_name: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        token_usage_json: dict[str, Any] | None = None,
        cost_json: dict[str, Any] | None = None,
        retry_count: int = 0,
        error_message: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> QaTraceSpan:
        span = QaTraceSpan(
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            span_order=span_order or self.next_span_order(trace_id),
            span_type=span_type,
            input_json=to_json_dict(input_json),
            output_json=to_json_dict(output_json) if output_json is not None else None,
            latency_ms=max(latency_ms, 0),
            status=status,
            error_message=error_message,
            started_at=started_at,
            ended_at=ended_at,
            model_name=model_name,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            token_usage_json=to_json_dict(token_usage_json or {}),
            cost_json=to_json_dict(cost_json or {}),
            retry_count=retry_count,
        )
        self.db.add(span)
        self.db.flush()
        return span

    def finish_trace(
        self,
        *,
        trace_id: UUID,
        route_type: str | None,
        final_answer: str,
        status: str,
        latency_ms: int,
    ) -> QaTrace:
        trace = self.db.get(QaTrace, trace_id)
        if trace is None:
            raise ValueError(f"Trace not found: {trace_id}")
        trace.route_type = route_type
        trace.final_answer = final_answer
        trace.status = status
        trace.latency_ms = max(latency_ms, 0)
        self.db.flush()
        return trace

    def next_span_order(self, trace_id: UUID) -> int:
        current = self.db.scalar(
            select(func.max(QaTraceSpan.span_order)).where(QaTraceSpan.trace_id == trace_id)
        )
        return int(current or 0) + 1

    def list_traces(
        self,
        *,
        page: int,
        page_size: int,
        user_id: UUID,
        include_all: bool,
        status: str | None = None,
        route_type: str | None = None,
    ) -> tuple[list[QaTrace], int]:
        filters = []
        if not include_all:
            filters.append(QaTrace.user_id == user_id)
        if status:
            filters.append(QaTrace.status == status)
        if route_type:
            filters.append(QaTrace.route_type == route_type)

        total = self.db.scalar(select(func.count(QaTrace.id)).where(*filters)) or 0
        items = list(
            self.db.scalars(
                select(QaTrace)
                .where(*filters)
                .order_by(QaTrace.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, int(total)

    def get_trace_with_spans(
        self,
        *,
        trace_id: UUID,
        user_id: UUID,
        include_all: bool,
    ) -> tuple[QaTrace, list[QaTraceSpan]]:
        filters = [QaTrace.id == trace_id]
        if not include_all:
            filters.append(QaTrace.user_id == user_id)

        trace = self.db.scalar(select(QaTrace).where(*filters))
        if trace is None:
            raise TraceNotFoundError(f"Trace not found: {trace_id}")

        spans = list(
            self.db.scalars(
                select(QaTraceSpan)
                .where(QaTraceSpan.trace_id == trace.id)
                .order_by(QaTraceSpan.span_order)
            )
        )
        return trace, spans


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_json_dict(value: Any) -> dict[str, Any]:
    encoded = jsonable_encoder(value)
    if isinstance(encoded, dict):
        return encoded
    return {"value": encoded}
