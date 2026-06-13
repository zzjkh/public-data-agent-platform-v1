"""semantic metadata

Revision ID: 009_semantic_metadata
Revises: 008_reporting_views_metadata
Create Date: 2026-06-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009_semantic_metadata"
down_revision = "008_reporting_views_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_metadata_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("metadata_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "aliases_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("business_meaning", sa.Text(), nullable=True),
        sa.Column("related_table", sa.String(length=255), server_default="", nullable=False),
        sa.Column("related_field", sa.String(length=255), server_default="", nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("time_grain", sa.String(length=64), nullable=True),
        sa.Column("ddl_snippet", sa.Text(), nullable=True),
        sa.Column("sql_example", sa.Text(), nullable=True),
        sa.Column("join_path", sa.Text(), nullable=True),
        sa.Column("embedding_text", sa.Text(), nullable=False),
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
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "metadata_type in ('dataset', 'table', 'field', 'metric', 'sql_example', 'business_rule')",
            name="ck_semantic_metadata_items_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "metadata_type",
            "name",
            "related_table",
            "related_field",
            name="uq_semantic_metadata_items_identity",
        ),
    )
    op.create_index(
        "ix_semantic_metadata_items_type",
        "semantic_metadata_items",
        ["metadata_type"],
        unique=False,
    )
    op.create_index(
        "ix_semantic_metadata_items_related",
        "semantic_metadata_items",
        ["related_table", "related_field"],
        unique=False,
    )
    op.create_index(
        "ix_semantic_metadata_items_search_tsv",
        "semantic_metadata_items",
        ["search_tsv"],
        unique=False,
        postgresql_using="gin",
    )

    op.execute(
        """
        CREATE TABLE semantic_metadata_embeddings (
            id uuid PRIMARY KEY,
            metadata_item_id uuid NOT NULL REFERENCES semantic_metadata_items(id) ON DELETE CASCADE,
            embedding_model varchar(255) NOT NULL,
            embedding_dim integer NOT NULL,
            embedding_version varchar(64) NOT NULL,
            embedding vector(512) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_semantic_metadata_embeddings_model_version
                UNIQUE (metadata_item_id, embedding_model, embedding_version)
        )
        """
    )
    op.create_index(
        "ix_semantic_metadata_embeddings_item_id",
        "semantic_metadata_embeddings",
        ["metadata_item_id"],
        unique=False,
    )
    op.execute(
        """
        CREATE INDEX ix_semantic_metadata_embeddings_hnsw
        ON semantic_metadata_embeddings
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_semantic_metadata_embeddings_hnsw")
    op.drop_index(
        "ix_semantic_metadata_embeddings_item_id",
        table_name="semantic_metadata_embeddings",
    )
    op.drop_table("semantic_metadata_embeddings")

    op.drop_index(
        "ix_semantic_metadata_items_search_tsv",
        table_name="semantic_metadata_items",
        postgresql_using="gin",
    )
    op.drop_index("ix_semantic_metadata_items_related", table_name="semantic_metadata_items")
    op.drop_index("ix_semantic_metadata_items_type", table_name="semantic_metadata_items")
    op.drop_table("semantic_metadata_items")
