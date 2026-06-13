"""qa traces

Revision ID: 010_qa_traces
Revises: 009_semantic_metadata
Create Date: 2026-06-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "010_qa_traces"
down_revision = "009_semantic_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qa_traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("route_type", sa.String(length=32), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "route_type is null or route_type in ('POLICY_QA', 'DATA_QA', 'HYBRID_QA', 'OTHER')",
            name="ck_qa_traces_route_type",
        ),
        sa.CheckConstraint(
            "status in ('running', 'success', 'failed', 'refused')",
            name="ck_qa_traces_status",
        ),
        sa.CheckConstraint("latency_ms is null or latency_ms >= 0", name="ck_qa_traces_latency"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_traces_user_created", "qa_traces", ["user_id", "created_at"], unique=False)
    op.create_index("ix_qa_traces_route_type", "qa_traces", ["route_type"], unique=False)

    op.create_table(
        "qa_trace_spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_span_id", sa.Uuid(), nullable=True),
        sa.Column("span_order", sa.Integer(), nullable=False),
        sa.Column("span_type", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("prompt_name", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("token_usage_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("cost_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("span_order >= 1", name="ck_qa_trace_spans_order"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_qa_trace_spans_latency"),
        sa.CheckConstraint("status in ('success', 'failed', 'skipped')", name="ck_qa_trace_spans_status"),
        sa.CheckConstraint("retry_count >= 0", name="ck_qa_trace_spans_retry_count"),
        sa.ForeignKeyConstraint(["trace_id"], ["qa_traces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_span_id"], ["qa_trace_spans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", "span_order", name="uq_qa_trace_spans_trace_order"),
    )
    op.create_index("ix_qa_trace_spans_trace_created", "qa_trace_spans", ["trace_id", "created_at"], unique=False)
    op.create_index("ix_qa_trace_spans_span_type", "qa_trace_spans", ["span_type"], unique=False)
    op.create_index("ix_qa_trace_spans_parent_span_id", "qa_trace_spans", ["parent_span_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_qa_trace_spans_parent_span_id", table_name="qa_trace_spans")
    op.drop_index("ix_qa_trace_spans_span_type", table_name="qa_trace_spans")
    op.drop_index("ix_qa_trace_spans_trace_created", table_name="qa_trace_spans")
    op.drop_table("qa_trace_spans")
    op.drop_index("ix_qa_traces_route_type", table_name="qa_traces")
    op.drop_index("ix_qa_traces_user_created", table_name="qa_traces")
    op.drop_table("qa_traces")
