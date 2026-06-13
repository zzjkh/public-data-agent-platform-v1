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


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        CheckConstraint(
            "chunk_strategy in ('section', 'paragraph', 'sliding_window')",
            name="ck_rag_chunks_strategy",
        ),
        UniqueConstraint("version_id", "content_hash", name="uq_rag_chunks_version_content_hash"),
        Index("ix_rag_chunks_version_order", "version_id", "order_index"),
        Index("ix_rag_chunks_version_id", "version_id"),
        Index("ix_rag_chunks_content_hash", "content_hash"),
        Index("ix_rag_chunks_prev_chunk_id", "prev_chunk_id"),
        Index("ix_rag_chunks_next_chunk_id", "next_chunk_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text)
    element_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    order_index: Mapped[int] = mapped_column(nullable=False)
    chunk_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    char_count: Mapped[int] = mapped_column(nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_chunks.id", ondelete="SET NULL"),
    )
    next_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_chunks.id", ondelete="SET NULL"),
    )
    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_tsv: Mapped[Any | None] = mapped_column(Text, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "embedding_model",
            "embedding_version",
            name="uq_chunk_embeddings_model_version",
        ),
        Index("ix_chunk_embeddings_chunk_id", "chunk_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_chunks.id", ondelete="CASCADE"),
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
