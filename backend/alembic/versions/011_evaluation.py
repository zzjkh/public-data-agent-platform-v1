"""evaluation

Revision ID: 011_evaluation
Revises: 010_qa_traces
Create Date: 2026-06-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "011_evaluation"
down_revision = "010_qa_traces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_type", sa.String(length=32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_route_type", sa.String(length=32), nullable=True),
        sa.Column("expected_behavior", sa.Text(), nullable=True),
        sa.Column("expected_sources_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("expected_view", sa.String(length=128), nullable=True),
        sa.Column("expected_metric_codes_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("expected_sql_pattern", sa.Text(), nullable=True),
        sa.Column("expected_sql_result_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("expected_keywords_json", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("judge_model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("case_type in ('rag', 'sql', 'hybrid', 'safety')", name="ck_eval_cases_case_type"),
        sa.CheckConstraint(
            "expected_route_type is null or expected_route_type in ('POLICY_QA', 'DATA_QA', 'HYBRID_QA', 'OTHER')",
            name="ck_eval_cases_expected_route_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_type", "question", name="uq_eval_cases_case_type_question"),
    )
    op.create_index("ix_eval_cases_case_type_enabled", "eval_cases", ["case_type", "enabled"], unique=False)
    op.create_index("ix_eval_cases_expected_route_type", "eval_cases", ["expected_route_type"], unique=False)

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("judge_model", sa.String(length=128), nullable=True),
        sa.Column("prompt_versions_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("run_config_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('pending', 'running', 'success', 'failed')", name="ck_eval_runs_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_status_started", "eval_runs", ["status", "started_at"], unique=False)

    op.create_table(
        "eval_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=False),
        sa.Column("eval_case_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("sql_valid", sa.Boolean(), nullable=True),
        sa.Column("citation_score", sa.Float(), nullable=True),
        sa.Column("groundedness_score", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("retrieval_score is null or retrieval_score >= 0", name="ck_eval_results_retrieval_score"),
        sa.CheckConstraint("citation_score is null or citation_score >= 0", name="ck_eval_results_citation_score"),
        sa.CheckConstraint(
            "groundedness_score is null or groundedness_score >= 0",
            name="ck_eval_results_groundedness_score",
        ),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["eval_case_id"], ["eval_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trace_id"], ["qa_traces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_results_eval_run_id", "eval_results", ["eval_run_id"], unique=False)
    op.create_index("ix_eval_results_trace_id", "eval_results", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_eval_results_trace_id", table_name="eval_results")
    op.drop_index("ix_eval_results_eval_run_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_status_started", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_expected_route_type", table_name="eval_cases")
    op.drop_index("ix_eval_cases_case_type_enabled", table_name="eval_cases")
    op.drop_table("eval_cases")
