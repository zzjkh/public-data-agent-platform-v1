"""ingestion jobs

Revision ID: 004_ingestion_jobs
Revises: 003_source_files_and_documents
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_ingestion_jobs"
down_revision = "003_source_files_and_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_percent", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'running', 'success', 'partial', 'failed', 'cancelled')",
            name="ck_ingestion_jobs_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 and progress_percent <= 100",
            name="ck_ingestion_jobs_progress",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_ingestion_jobs_retry_count"),
        sa.CheckConstraint("max_retries >= 0", name="ck_ingestion_jobs_max_retries"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_jobs_status_priority_created",
        "ingestion_jobs",
        ["status", "priority", "created_at"],
        unique=False,
    )
    op.create_index("ix_ingestion_jobs_target", "ingestion_jobs", ["target_type", "target_id"], unique=False)
    op.create_index("ix_ingestion_jobs_locked_at", "ingestion_jobs", ["locked_at"], unique=False)
    op.create_index("ix_ingestion_jobs_heartbeat_at", "ingestion_jobs", ["heartbeat_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_heartbeat_at", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_locked_at", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_target", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_status_priority_created", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
