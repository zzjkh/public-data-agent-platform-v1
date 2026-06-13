from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DatasetImportRequest(BaseModel):
    catalog_source_file_id: UUID
    fields_source_file_id: UUID | None = None
    priority: int = Field(default=100, ge=0, le=1000)
    max_retries: int | None = Field(default=None, ge=0, le=10)


class MetricImportRequest(BaseModel):
    source_file_id: UUID
    format: str = Field(default="auto", pattern="^(auto|long|wide)$")
    default_region_code: str | None = None
    default_region_name: str = "北京市"
    default_stat_period: str = Field(default="annual", pattern="^(annual|quarterly|monthly)$")
    default_data_version: str = "v1"
    default_source: str | None = None
    default_source_url: str | None = None
    metric_mappings: dict[str, dict[str, Any]] | None = None
    priority: int = Field(default=100, ge=0, le=1000)
    max_retries: int | None = Field(default=None, ge=0, le=10)


class OpenDatasetFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    field_name: str
    field_type: str | None
    description: str | None
    example_value: str | None
    is_dimension: bool
    is_measure: bool
    created_at: datetime
    updated_at: datetime


class OpenDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    category: str | None
    department: str | None
    owner: str | None
    source_platform: str | None
    source_url: str | None
    open_type: str | None
    update_frequency: str | None
    update_date: date | None
    time_range: str | None
    region_level: str | None
    sensitivity_level: str | None
    download_count: int
    api_count: int
    status: str
    last_synced_at: datetime | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class OpenDatasetListResponse(BaseModel):
    items: list[OpenDatasetRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class OpenDatasetDetailResponse(OpenDatasetRead):
    fields: list[OpenDatasetFieldRead]
    request_id: str


class MetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    indicator_code: str
    indicator_name: str
    domain: str
    unit: str | None
    description: str | None
    aliases_json: list[str]
    source_dataset_id: UUID | None
    created_at: datetime
    updated_at: datetime


class MetricValueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    metric_id: UUID
    indicator_code: str
    indicator_name: str
    region_code: str | None
    region_name: str
    stat_period: str
    stat_year: int | None
    stat_month: int | None
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    dimension_json: dict[str, Any]
    source: str | None
    source_url: str | None
    data_version: str
    created_at: datetime


class MetricListResponse(BaseModel):
    items: list[MetricRead]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    request_id: str


class MetricValueListResponse(BaseModel):
    metric: MetricRead
    items: list[MetricValueRead]
    total: int = Field(ge=0)
    request_id: str
