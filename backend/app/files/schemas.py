from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_name: str
    file_type: str
    storage_uri: str
    source_url: str | None
    file_hash: str
    file_version: str
    parse_status: str
    error_message: str | None
    uploaded_by: UUID | None
    uploaded_at: datetime


class SourceFileUploadResponse(BaseModel):
    file_id: UUID
    storage_uri: str
    file_hash: str
    parse_status: str
    request_id: str


class SourceFileListResponse(BaseModel):
    items: list[SourceFileRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str
