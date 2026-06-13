"""datasets and metrics

Revision ID: 006_datasets_metrics
Revises: 005_rag_chunks_embeddings
Create Date: 2026-06-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_datasets_metrics"
down_revision = "005_rag_chunks_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "open_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("owner", sa.String(length=255), nullable=True),
        sa.Column("source_platform", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("open_type", sa.String(length=64), nullable=True),
        sa.Column("update_frequency", sa.String(length=64), nullable=True),
        sa.Column("update_date", sa.Date(), nullable=True),
        sa.Column("time_range", sa.String(length=128), nullable=True),
        sa.Column("region_level", sa.String(length=32), nullable=True),
        sa.Column("sensitivity_level", sa.String(length=32), nullable=True),
        sa.Column("download_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("api_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('active', 'archived')", name="ck_open_datasets_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "source_url", name="uq_open_datasets_name_source_url"),
    )
    op.create_index("ix_open_datasets_category", "open_datasets", ["category"], unique=False)
    op.create_index("ix_open_datasets_department", "open_datasets", ["department"], unique=False)
    op.create_index("ix_open_datasets_source_url", "open_datasets", ["source_url"], unique=False)
    op.create_index("ix_open_datasets_status", "open_datasets", ["status"], unique=False)

    op.create_table(
        "open_dataset_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("example_value", sa.Text(), nullable=True),
        sa.Column("is_dimension", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_measure", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["open_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "field_name", name="uq_open_dataset_fields_dataset_field"),
    )
    op.create_index(
        "ix_open_dataset_fields_dataset_id",
        "open_dataset_fields",
        ["dataset_id"],
        unique=False,
    )
    op.create_index(
        "ix_open_dataset_fields_field_type",
        "open_dataset_fields",
        ["field_type"],
        unique=False,
    )

    op.create_table(
        "metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("indicator_code", sa.String(length=128), nullable=False),
        sa.Column("indicator_name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=32), server_default="other", nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "aliases_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_dataset_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "domain in ('economy', 'population', 'open_data', 'other')",
            name="ck_metrics_domain",
        ),
        sa.ForeignKeyConstraint(["source_dataset_id"], ["open_datasets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("indicator_code", name="uq_metrics_indicator_code"),
    )
    op.create_index("ix_metrics_indicator_code", "metrics", ["indicator_code"], unique=False)
    op.create_index("ix_metrics_domain", "metrics", ["domain"], unique=False)

    op.create_table(
        "metric_values",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("metric_id", sa.Uuid(), nullable=False),
        sa.Column("indicator_code", sa.String(length=128), nullable=False),
        sa.Column("indicator_name", sa.String(length=255), nullable=False),
        sa.Column("region_code", sa.String(length=64), nullable=True),
        sa.Column("region_name", sa.String(length=255), nullable=False),
        sa.Column("stat_period", sa.String(length=16), server_default="annual", nullable=False),
        sa.Column("stat_year", sa.Integer(), nullable=True),
        sa.Column("stat_month", sa.Integer(), nullable=True),
        sa.Column("value_numeric", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column(
            "dimension_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("data_version", sa.String(length=64), server_default="v1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "stat_period in ('annual', 'quarterly', 'monthly')",
            name="ck_metric_values_stat_period",
        ),
        sa.ForeignKeyConstraint(["metric_id"], ["metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "metric_id",
            "region_name",
            "stat_period",
            "stat_year",
            "stat_month",
            "dimension_json",
            name="uq_metric_values_metric_region_period_dimension",
        ),
    )
    op.create_index(
        "ix_metric_values_metric_region_year",
        "metric_values",
        ["metric_id", "region_name", "stat_year"],
        unique=False,
    )
    op.create_index(
        "ix_metric_values_indicator_code",
        "metric_values",
        ["indicator_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_metric_values_indicator_code", table_name="metric_values")
    op.drop_index("ix_metric_values_metric_region_year", table_name="metric_values")
    op.drop_table("metric_values")

    op.drop_index("ix_metrics_domain", table_name="metrics")
    op.drop_index("ix_metrics_indicator_code", table_name="metrics")
    op.drop_table("metrics")

    op.drop_index("ix_open_dataset_fields_field_type", table_name="open_dataset_fields")
    op.drop_index("ix_open_dataset_fields_dataset_id", table_name="open_dataset_fields")
    op.drop_table("open_dataset_fields")

    op.drop_index("ix_open_datasets_status", table_name="open_datasets")
    op.drop_index("ix_open_datasets_source_url", table_name="open_datasets")
    op.drop_index("ix_open_datasets_department", table_name="open_datasets")
    op.drop_index("ix_open_datasets_category", table_name="open_datasets")
    op.drop_table("open_datasets")
