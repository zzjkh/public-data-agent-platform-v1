"""add metric value source url

Revision ID: 007_metric_values_source_url
Revises: 006_datasets_metrics
Create Date: 2026-06-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "007_metric_values_source_url"
down_revision = "006_datasets_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("metric_values", sa.Column("source_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("metric_values", "source_url")
