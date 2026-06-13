from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.llm.contracts import ChartSpec, RouteType


class QaAskOptions(BaseModel):
    return_trace: bool = False


class QaAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    options: QaAskOptions = Field(default_factory=QaAskOptions)


class QaCitation(BaseModel):
    type: Literal["policy", "data"] = "policy"
    source_title: str
    source_url: str | None = None
    section_path: str | None = None
    quote: str | None = None


class QaSqlPayload(BaseModel):
    validated_sql: str
    row_count: int
    columns: list[str] = Field(default_factory=list)
    result_preview: list[dict[str, Any]] = Field(default_factory=list)


class QaResponse(BaseModel):
    trace_id: UUID
    route_type: RouteType
    answer: str
    citations: list[QaCitation] = Field(default_factory=list)
    sql: QaSqlPayload | None = None
    chart: ChartSpec | None = None
    request_id: str
