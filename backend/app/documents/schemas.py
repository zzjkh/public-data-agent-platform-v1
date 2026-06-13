from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentElementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    version_id: UUID
    element_type: str
    content: str
    page_no: int | None
    order_index: int
    parent_id: UUID | None
    heading_level: int | None
    bbox_json: dict | None
    metadata_json: dict


class DocumentElementListResponse(BaseModel):
    items: list[DocumentElementRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class RagChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    version_id: UUID
    chunk_text: str
    embedding_text: str
    retrieval_text: str
    heading_path: str | None
    element_ids_json: list[str]
    order_index: int
    chunk_strategy: str
    char_count: int
    token_count: int
    content_hash: str
    prev_chunk_id: UUID | None
    next_chunk_id: UUID | None
    search_text: str


class RagChunkListResponse(BaseModel):
    items: list[RagChunkRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class DocumentVersionPublishRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    issuing_agency: str | None = Field(default=None, max_length=255)
    document_no: str | None = Field(default=None, max_length=128)
    publish_date: date | None = None
    topic: str | None = Field(default=None, max_length=128)
    policy_level: Literal["national", "province", "city", "district"] | None = None
    validity_status: Literal["active", "expired", "abolished", "unknown"] | None = None
    keywords: list[str] | None = None


class DocumentVersionPublishResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    publish_status: str
    published_at: datetime
    archived_version_ids: list[UUID]
    request_id: str
