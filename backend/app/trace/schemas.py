from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TraceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    user_question: str
    route_type: str | None
    final_answer: str | None
    status: str
    latency_ms: int | None
    created_at: datetime


class TraceSpanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: UUID
    parent_span_id: UUID | None
    span_order: int
    span_type: str
    input_json: dict[str, Any]
    output_json: dict[str, Any] | None
    latency_ms: int
    status: str
    error_message: str | None
    started_at: datetime | None
    ended_at: datetime | None
    model_name: str | None
    prompt_name: str | None
    prompt_version: str | None
    token_usage_json: dict[str, Any]
    cost_json: dict[str, Any]
    retry_count: int
    created_at: datetime


class TraceListResponse(BaseModel):
    items: list[TraceRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class TraceDetailResponse(TraceRead):
    spans: list[TraceSpanRead]
    request_id: str
