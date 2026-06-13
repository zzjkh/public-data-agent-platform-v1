from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReportingView(Base):
    __tablename__ = "reporting_views"
    __table_args__ = (
        UniqueConstraint("schema_name", "view_name", name="uq_reporting_views_schema_view"),
        Index("ix_reporting_views_enabled", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    schema_name: Mapped[str] = mapped_column(String(64), nullable=False, default="reporting")
    view_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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


class ReportingViewField(Base):
    __tablename__ = "reporting_view_fields"
    __table_args__ = (
        UniqueConstraint("view_id", "field_name", name="uq_reporting_view_fields_view_field"),
        Index("ix_reporting_view_fields_view_id", "view_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    view_id: Mapped[UUID] = mapped_column(
        ForeignKey("reporting_views.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_type: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    is_dimension: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_measure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_filter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_group_by: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    example_value: Mapped[str | None] = mapped_column(Text)
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
