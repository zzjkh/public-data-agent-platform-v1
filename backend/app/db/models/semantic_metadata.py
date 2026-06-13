from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


SEMANTIC_METADATA_TYPES = ("dataset", "table", "field", "metric", "sql_example", "business_rule")


class SemanticMetadataItem(Base):
    __tablename__ = "semantic_metadata_items"
    __table_args__ = (
        CheckConstraint(
            "metadata_type in ('dataset', 'table', 'field', 'metric', 'sql_example', 'business_rule')",
            name="ck_semantic_metadata_items_type",
        ),
        UniqueConstraint(
            "metadata_type",
            "name",
            "related_table",
            "related_field",
            name="uq_semantic_metadata_items_identity",
        ),
        Index("ix_semantic_metadata_items_type", "metadata_type"),
        Index("ix_semantic_metadata_items_related", "related_table", "related_field"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    metadata_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    business_meaning: Mapped[str | None] = mapped_column(Text)
    related_table: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    related_field: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    unit: Mapped[str | None] = mapped_column(String(64))
    time_grain: Mapped[str | None] = mapped_column(String(64))
    ddl_snippet: Mapped[str | None] = mapped_column(Text)
    sql_example: Mapped[str | None] = mapped_column(Text)
    join_path: Mapped[str | None] = mapped_column(Text)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_tsv: Mapped[Any | None] = mapped_column(Text, server_default=FetchedValue())
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


class SemanticMetadataEmbedding(Base):
    __tablename__ = "semantic_metadata_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "metadata_item_id",
            "embedding_model",
            "embedding_version",
            name="uq_semantic_metadata_embeddings_model_version",
        ),
        Index("ix_semantic_metadata_embeddings_item_id", "metadata_item_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    metadata_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("semantic_metadata_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
