from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EvalCaseType = Literal["rag", "sql", "hybrid", "safety"]
EvalRouteType = Literal["POLICY_QA", "DATA_QA", "HYBRID_QA", "OTHER"]
EvalRunStatus = Literal["pending", "running", "success", "failed"]


class EvalCaseCreateRequest(BaseModel):
    case_type: EvalCaseType
    question: str = Field(min_length=1, max_length=1000)
    expected_route_type: EvalRouteType | None = None
    expected_behavior: str | None = None
    expected_sources_json: list[str] = Field(default_factory=list)
    expected_view: str | None = None
    expected_metric_codes_json: list[str] = Field(default_factory=list)
    expected_sql_pattern: str | None = None
    expected_sql_result_json: dict[str, Any] = Field(default_factory=dict)
    expected_keywords_json: list[str] = Field(default_factory=list)
    judge_model: str | None = None
    prompt_version: str | None = None
    enabled: bool = True


class EvalCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_type: str
    question: str
    expected_route_type: str | None
    expected_behavior: str | None
    expected_sources_json: list[str]
    expected_view: str | None
    expected_metric_codes_json: list[str]
    expected_sql_pattern: str | None
    expected_sql_result_json: dict[str, Any]
    expected_keywords_json: list[str]
    judge_model: str | None
    prompt_version: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class EvalCaseListResponse(BaseModel):
    items: list[EvalCaseRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class EvalRunCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    case_types: list[EvalCaseType] = Field(default_factory=lambda: ["rag", "sql", "hybrid", "safety"])
    case_ids: list[UUID] = Field(default_factory=list)


class EvalRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    model_name: str
    embedding_model: str
    judge_model: str | None
    prompt_versions_json: dict[str, Any]
    run_config_json: dict[str, Any]
    status: EvalRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EvalRunListResponse(BaseModel):
    items: list[EvalRunRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class EvalResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    eval_run_id: UUID
    eval_case_id: UUID
    trace_id: UUID | None
    passed: bool
    retrieval_score: float | None
    sql_valid: bool | None
    citation_score: float | None
    groundedness_score: float | None
    error_message: str | None
    metrics_json: dict[str, Any]
    created_at: datetime


class EvalRunDetailResponse(EvalRunRead):
    results: list[EvalResultRead]
    request_id: str


class EvalImportSummary(BaseModel):
    upserted: int
    created: int
    updated: int
    files: list[str]
