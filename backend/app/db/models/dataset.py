from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OpenDataset(Base):
    __tablename__ = "open_datasets"
    __table_args__ = (
        CheckConstraint("status in ('active', 'archived')", name="ck_open_datasets_status"),
        UniqueConstraint("name", "source_url", name="uq_open_datasets_name_source_url"),
        Index("ix_open_datasets_category", "category"),
        Index("ix_open_datasets_department", "department"),
        Index("ix_open_datasets_source_url", "source_url"),
        Index("ix_open_datasets_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128))
    department: Mapped[str | None] = mapped_column(String(255))
    owner: Mapped[str | None] = mapped_column(String(255))
    source_platform: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    open_type: Mapped[str | None] = mapped_column(String(64))
    update_frequency: Mapped[str | None] = mapped_column(String(64))
    update_date: Mapped[date | None] = mapped_column(Date())
    time_range: Mapped[str | None] = mapped_column(String(128))
    region_level: Mapped[str | None] = mapped_column(String(32))
    sensitivity_level: Mapped[str | None] = mapped_column(String(32))
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OpenDatasetField(Base):
    __tablename__ = "open_dataset_fields"
    __table_args__ = (
        UniqueConstraint("dataset_id", "field_name", name="uq_open_dataset_fields_dataset_field"),
        Index("ix_open_dataset_fields_dataset_id", "dataset_id"),
        Index("ix_open_dataset_fields_field_type", "field_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("open_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    example_value: Mapped[str | None] = mapped_column(Text)
    is_dimension: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_measure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        CheckConstraint("domain in ('economy', 'population', 'open_data', 'other')", name="ck_metrics_domain"),
        UniqueConstraint("indicator_code", name="uq_metrics_indicator_code"),
        Index("ix_metrics_indicator_code", "indicator_code"),
        Index("ix_metrics_domain", "domain"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    indicator_code: Mapped[str] = mapped_column(String(128), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    unit: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_dataset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("open_datasets.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MetricValue(Base):
    __tablename__ = "metric_values"
    __table_args__ = (
        CheckConstraint(
            "stat_period in ('annual', 'quarterly', 'monthly')",
            name="ck_metric_values_stat_period",
        ),
        UniqueConstraint(
            "metric_id",
            "region_name",
            "stat_period",
            "stat_year",
            "stat_month",
            "dimension_json",
            name="uq_metric_values_metric_region_period_dimension",
        ),
        Index("ix_metric_values_metric_region_year", "metric_id", "region_name", "stat_year"),
        Index("ix_metric_values_indicator_code", "indicator_code"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    metric_id: Mapped[UUID] = mapped_column(ForeignKey("metrics.id", ondelete="CASCADE"), nullable=False)
    indicator_code: Mapped[str] = mapped_column(String(128), nullable=False)
    indicator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    region_code: Mapped[str | None] = mapped_column(String(64))
    region_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stat_period: Mapped[str] = mapped_column(String(16), nullable=False, default="annual")
    stat_year: Mapped[int | None] = mapped_column(Integer)
    stat_month: Mapped[int | None] = mapped_column(Integer)
    value_numeric: Mapped[float | None] = mapped_column()
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(64))
    dimension_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    data_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
