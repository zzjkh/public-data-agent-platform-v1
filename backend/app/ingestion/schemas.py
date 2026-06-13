from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobCreateRequest(BaseModel):
    job_type: str = Field(min_length=1, max_length=64)
    target_type: str = Field(min_length=1, max_length=64)
    target_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    max_retries: int | None = Field(default=None, ge=0, le=10)


class JobCreateResponse(BaseModel):
    job_id: UUID
    status: str
    request_id: str


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    target_type: str
    target_id: UUID | None
    status: str
    priority: int
    payload_json: dict[str, Any]
    result_json: dict[str, Any] | None
    error_message: str | None
    retry_count: int
    max_retries: int
    locked_by: str | None
    locked_at: datetime | None
    heartbeat_at: datetime | None
    progress_percent: int
    created_by: UUID | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    request_id: str | None = None


class JobListResponse(BaseModel):
    items: list[JobRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str
