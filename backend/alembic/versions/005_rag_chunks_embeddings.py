"""rag chunks and embeddings

Revision ID: 005_rag_chunks_embeddings
Revises: 004_ingestion_jobs
Create Date: 2026-06-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_rag_chunks_embeddings"
down_revision = "004_ingestion_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=False),
        sa.Column("retrieval_text", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column(
            "element_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("chunk_strategy", sa.String(length=32), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prev_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("next_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, coalesce(search_text, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "chunk_strategy in ('section', 'paragraph', 'sliding_window')",
            name="ck_rag_chunks_strategy",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["policy_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["policy_document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prev_chunk_id"], ["rag_chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["next_chunk_id"], ["rag_chunks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "content_hash", name="uq_rag_chunks_version_content_hash"),
    )
    op.create_index("ix_rag_chunks_version_order", "rag_chunks", ["version_id", "order_index"], unique=False)
    op.create_index("ix_rag_chunks_version_id", "rag_chunks", ["version_id"], unique=False)
    op.create_index("ix_rag_chunks_content_hash", "rag_chunks", ["content_hash"], unique=False)
    op.create_index("ix_rag_chunks_prev_chunk_id", "rag_chunks", ["prev_chunk_id"], unique=False)
    op.create_index("ix_rag_chunks_next_chunk_id", "rag_chunks", ["next_chunk_id"], unique=False)
    op.create_index(
        "ix_rag_chunks_search_tsv",
        "rag_chunks",
        ["search_tsv"],
        unique=False,
        postgresql_using="gin",
    )

    op.execute(
        """
        CREATE TABLE chunk_embeddings (
            id uuid PRIMARY KEY,
            chunk_id uuid NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
            embedding_model varchar(255) NOT NULL,
            embedding_dim integer NOT NULL,
            embedding_version varchar(64) NOT NULL,
            embedding vector(512) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_chunk_embeddings_model_version
                UNIQUE (chunk_id, embedding_model, embedding_version)
        )
        """
    )
    op.create_index("ix_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"], unique=False)
    op.execute(
        """
        CREATE INDEX ix_chunk_embeddings_hnsw
        ON chunk_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_hnsw")
    op.drop_index("ix_chunk_embeddings_chunk_id", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")

    op.drop_index("ix_rag_chunks_search_tsv", table_name="rag_chunks", postgresql_using="gin")
    op.drop_index("ix_rag_chunks_next_chunk_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_prev_chunk_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_content_hash", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_version_id", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_version_order", table_name="rag_chunks")
    op.drop_table("rag_chunks")
