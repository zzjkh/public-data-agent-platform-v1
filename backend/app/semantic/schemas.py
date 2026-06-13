from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SemanticMetadataType = Literal["dataset", "table", "field", "metric", "sql_example", "business_rule"]


class SemanticMetadataRebuildRequest(BaseModel):
    types: list[SemanticMetadataType] | None = None
    force_rebuild: bool = False
    priority: int = Field(default=100, ge=0, le=1000)
    max_retries: int | None = Field(default=None, ge=0, le=10)


class SemanticMetadataSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=50)
    metadata_types: list[SemanticMetadataType] | None = None


class SemanticMetadataItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    metadata_type: str
    name: str
    description: str | None
    aliases_json: list[str]
    business_meaning: str | None
    related_table: str
    related_field: str
    unit: str | None
    time_grain: str | None
    ddl_snippet: str | None
    sql_example: str | None
    join_path: str | None
    embedding_text: str
    search_text: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SemanticMetadataListResponse(BaseModel):
    items: list[SemanticMetadataItemRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class SemanticMetadataSearchHit(BaseModel):
    item: SemanticMetadataItemRead
    score: float
    dense_score: float
    keyword_score: float
    fulltext_score: float
    exact_score: float
    match_sources: list[str]


class SemanticMetadataSearchResponse(BaseModel):
    query: str
    items: list[SemanticMetadataSearchHit]
    request_id: str
