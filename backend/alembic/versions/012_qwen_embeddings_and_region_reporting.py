"""Qwen embeddings and region-aware reporting

Revision ID: 012_qwen_embeddings_region
Revises: 011_evaluation
Create Date: 2026-06-13
"""
from __future__ import annotations

from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa

revision = "012_qwen_embeddings_region"
down_revision = "011_evaluation"
branch_labels = None
depends_on = None

REPORTING_METADATA_NAMESPACE = UUID("8f0fb2dd-d5ea-42a6-a47a-9199b7e8d901")
METRIC_VIEWS = ("vw_population_yearly", "vw_gdp_yearly")
REGION_FIELDS = (
    ("region_code", "text", "行政区划代码，用于稳定识别地区。", True, False, True, False, "330100"),
    ("region_level", "text", "行政区层级，例如 province、city、district。", True, False, True, True, "city"),
    ("parent_region_name", "text", "上级行政区名称，用于省内城市或市内区县过滤。", True, False, True, True, "浙江省"),
    ("parent_region_code", "text", "上级行政区划代码。", True, False, True, False, "330000"),
)


def _view_id(view_name: str) -> UUID:
    return uuid5(REPORTING_METADATA_NAMESPACE, f"reporting.{view_name}")


def _field_id(view_name: str, field_name: str) -> UUID:
    return uuid5(REPORTING_METADATA_NAMESPACE, f"reporting.{view_name}.{field_name}")


def upgrade() -> None:
    _archive_512_embedding_tables()
    _create_1024_embedding_tables()
    _recreate_metric_views(region_aware=True)
    _insert_region_metadata_fields()


def downgrade() -> None:
    _delete_region_metadata_fields()
    _recreate_metric_views(region_aware=False)
    _drop_1024_embedding_tables()
    _restore_512_embedding_tables()


def _archive_512_embedding_tables() -> None:
    op.execute("ALTER INDEX ix_chunk_embeddings_hnsw RENAME TO ix_chunk_embeddings_512_legacy_hnsw")
    op.execute("ALTER INDEX ix_chunk_embeddings_chunk_id RENAME TO ix_chunk_embeddings_512_legacy_chunk_id")
    op.execute("ALTER TABLE chunk_embeddings RENAME TO chunk_embeddings_512_legacy")
    op.execute(
        "ALTER TABLE chunk_embeddings_512_legacy "
        "RENAME CONSTRAINT chunk_embeddings_pkey TO chunk_embeddings_512_legacy_pkey"
    )
    op.execute(
        "ALTER TABLE chunk_embeddings_512_legacy "
        "RENAME CONSTRAINT chunk_embeddings_chunk_id_fkey "
        "TO chunk_embeddings_512_legacy_chunk_id_fkey"
    )
    op.execute(
        "ALTER TABLE chunk_embeddings_512_legacy "
        "RENAME CONSTRAINT uq_chunk_embeddings_model_version "
        "TO uq_chunk_embeddings_512_legacy_model_version"
    )

    op.execute(
        "ALTER INDEX ix_semantic_metadata_embeddings_hnsw "
        "RENAME TO ix_semantic_metadata_embeddings_512_legacy_hnsw"
    )
    op.execute(
        "ALTER INDEX ix_semantic_metadata_embeddings_item_id "
        "RENAME TO ix_semantic_metadata_embeddings_512_legacy_item_id"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings "
        "RENAME TO semantic_metadata_embeddings_512_legacy"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings_512_legacy "
        "RENAME CONSTRAINT semantic_metadata_embeddings_pkey "
        "TO semantic_metadata_embeddings_512_legacy_pkey"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings_512_legacy "
        "RENAME CONSTRAINT semantic_metadata_embeddings_metadata_item_id_fkey "
        "TO semantic_metadata_embeddings_512_legacy_item_id_fkey"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings_512_legacy "
        "RENAME CONSTRAINT uq_semantic_metadata_embeddings_model_version "
        "TO uq_semantic_metadata_embeddings_512_legacy_model_version"
    )


def _create_1024_embedding_tables() -> None:
    op.execute(
        """
        CREATE TABLE chunk_embeddings (
            id uuid PRIMARY KEY,
            chunk_id uuid NOT NULL REFERENCES rag_chunks(id) ON DELETE CASCADE,
            embedding_model varchar(255) NOT NULL,
            embedding_dim integer NOT NULL,
            embedding_version varchar(64) NOT NULL,
            embedding vector(1024) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_chunk_embeddings_model_version
                UNIQUE (chunk_id, embedding_model, embedding_version)
        )
        """
    )
    op.create_index("ix_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"])
    op.execute(
        "CREATE INDEX ix_chunk_embeddings_hnsw ON chunk_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.execute(
        """
        CREATE TABLE semantic_metadata_embeddings (
            id uuid PRIMARY KEY,
            metadata_item_id uuid NOT NULL REFERENCES semantic_metadata_items(id) ON DELETE CASCADE,
            embedding_model varchar(255) NOT NULL,
            embedding_dim integer NOT NULL,
            embedding_version varchar(64) NOT NULL,
            embedding vector(1024) NOT NULL,
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
    )
    op.execute(
        "CREATE INDEX ix_semantic_metadata_embeddings_hnsw "
        "ON semantic_metadata_embeddings USING hnsw (embedding vector_cosine_ops)"
    )


def _drop_1024_embedding_tables() -> None:
    op.execute("DROP TABLE semantic_metadata_embeddings")
    op.execute("DROP TABLE chunk_embeddings")


def _restore_512_embedding_tables() -> None:
    op.execute("ALTER TABLE chunk_embeddings_512_legacy RENAME TO chunk_embeddings")
    op.execute(
        "ALTER TABLE chunk_embeddings "
        "RENAME CONSTRAINT chunk_embeddings_512_legacy_pkey TO chunk_embeddings_pkey"
    )
    op.execute(
        "ALTER TABLE chunk_embeddings "
        "RENAME CONSTRAINT chunk_embeddings_512_legacy_chunk_id_fkey "
        "TO chunk_embeddings_chunk_id_fkey"
    )
    op.execute(
        "ALTER TABLE chunk_embeddings "
        "RENAME CONSTRAINT uq_chunk_embeddings_512_legacy_model_version "
        "TO uq_chunk_embeddings_model_version"
    )
    op.execute("ALTER INDEX ix_chunk_embeddings_512_legacy_chunk_id RENAME TO ix_chunk_embeddings_chunk_id")
    op.execute("ALTER INDEX ix_chunk_embeddings_512_legacy_hnsw RENAME TO ix_chunk_embeddings_hnsw")

    op.execute(
        "ALTER TABLE semantic_metadata_embeddings_512_legacy "
        "RENAME TO semantic_metadata_embeddings"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings "
        "RENAME CONSTRAINT semantic_metadata_embeddings_512_legacy_pkey "
        "TO semantic_metadata_embeddings_pkey"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings "
        "RENAME CONSTRAINT semantic_metadata_embeddings_512_legacy_item_id_fkey "
        "TO semantic_metadata_embeddings_metadata_item_id_fkey"
    )
    op.execute(
        "ALTER TABLE semantic_metadata_embeddings "
        "RENAME CONSTRAINT uq_semantic_metadata_embeddings_512_legacy_model_version "
        "TO uq_semantic_metadata_embeddings_model_version"
    )
    op.execute(
        "ALTER INDEX ix_semantic_metadata_embeddings_512_legacy_item_id "
        "RENAME TO ix_semantic_metadata_embeddings_item_id"
    )
    op.execute(
        "ALTER INDEX ix_semantic_metadata_embeddings_512_legacy_hnsw "
        "RENAME TO ix_semantic_metadata_embeddings_hnsw"
    )


def _recreate_metric_views(*, region_aware: bool) -> None:
    for view_name, indicator_code in (
        ("vw_population_yearly", "resident_population"),
        ("vw_gdp_yearly", "gdp_total"),
    ):
        op.execute(f"DROP VIEW IF EXISTS reporting.{view_name}")
        region_columns = """
          mv.region_code,
          mv.dimension_json->>'region_level' AS region_level,
          mv.dimension_json->>'parent_region_name' AS parent_region_name,
          mv.dimension_json->>'parent_region_code' AS parent_region_code,
        """ if region_aware else ""
        op.execute(
            f"""
            CREATE VIEW reporting.{view_name} AS
            SELECT
              {region_columns}
              mv.region_name,
              mv.stat_year,
              m.indicator_name,
              mv.value_numeric,
              mv.unit,
              mv.source,
              mv.source_url,
              mv.data_version
            FROM metric_values mv
            JOIN metrics m ON mv.metric_id = m.id
            WHERE m.indicator_code = '{indicator_code}'
              AND mv.stat_period = 'annual'
            """
        )


def _insert_region_metadata_fields() -> None:
    fields = sa.table(
        "reporting_view_fields",
        sa.column("id", sa.Uuid()),
        sa.column("view_id", sa.Uuid()),
        sa.column("field_name", sa.String()),
        sa.column("field_type", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_dimension", sa.Boolean()),
        sa.column("is_measure", sa.Boolean()),
        sa.column("allowed_filter", sa.Boolean()),
        sa.column("allowed_group_by", sa.Boolean()),
        sa.column("example_value", sa.Text()),
    )
    rows = []
    for view_name in METRIC_VIEWS:
        for field in REGION_FIELDS:
            rows.append(
                {
                    "id": _field_id(view_name, field[0]),
                    "view_id": _view_id(view_name),
                    "field_name": field[0],
                    "field_type": field[1],
                    "description": field[2],
                    "is_dimension": field[3],
                    "is_measure": field[4],
                    "allowed_filter": field[5],
                    "allowed_group_by": field[6],
                    "example_value": field[7],
                }
            )
    op.bulk_insert(fields, rows)


def _delete_region_metadata_fields() -> None:
    field_names = ", ".join(f"'{field[0]}'" for field in REGION_FIELDS)
    view_ids = ", ".join(f"'{_view_id(view_name)}'" for view_name in METRIC_VIEWS)
    op.execute(
        f"DELETE FROM reporting_view_fields "
        f"WHERE view_id IN ({view_ids}) AND field_name IN ({field_names})"
    )
