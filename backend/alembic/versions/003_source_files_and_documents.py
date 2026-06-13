"""source files and policy documents

Revision ID: 003_source_files_and_documents
Revises: 002_auth
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003_source_files_and_documents"
down_revision = "002_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("storage_uri", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_version", sa.String(length=64), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("file_type in ('pdf', 'html', 'csv', 'xlsx')", name="ck_source_files_type"),
        sa.CheckConstraint(
            "parse_status in ('pending', 'parsed', 'partial', 'failed')",
            name="ck_source_files_parse_status",
        ),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_files_file_hash", "source_files", ["file_hash"], unique=True)
    op.create_index("ix_source_files_source_url", "source_files", ["source_url"], unique=False)
    op.create_index("ix_source_files_parse_status", "source_files", ["parse_status"], unique=False)

    op.create_table(
        "policy_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("issuing_agency", sa.String(length=255), nullable=True),
        sa.Column("document_no", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("topic", sa.String(length=128), nullable=True),
        sa.Column("policy_level", sa.String(length=16), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("abolished_date", sa.Date(), nullable=True),
        sa.Column("validity_status", sa.String(length=16), nullable=False),
        sa.Column(
            "keywords_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "policy_level in ('national', 'province', 'city', 'district')",
            name="ck_policy_documents_policy_level",
        ),
        sa.CheckConstraint(
            "validity_status in ('active', 'expired', 'abolished', 'unknown')",
            name="ck_policy_documents_validity_status",
        ),
        sa.CheckConstraint("status in ('active', 'archived')", name="ck_policy_documents_status"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_documents_source_url", "policy_documents", ["source_url"], unique=False)
    op.create_index("ix_policy_documents_policy_level", "policy_documents", ["policy_level"], unique=False)
    op.create_index(
        "ix_policy_documents_validity_status",
        "policy_documents",
        ["validity_status"],
        unique=False,
    )
    op.create_index(
        "ix_policy_documents_effective_date",
        "policy_documents",
        ["effective_date"],
        unique=False,
    )

    op.create_table(
        "policy_document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("clean_text", sa.Text(), nullable=True),
        sa.Column("markdown_text", sa.Text(), nullable=True),
        sa.Column(
            "parse_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("publish_status", sa.String(length=16), nullable=False),
        sa.Column("parser_type", sa.String(length=16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "publish_status in ('draft', 'published', 'archived')",
            name="ck_policy_document_versions_publish_status",
        ),
        sa.CheckConstraint(
            "parser_type in ('html', 'pdf_text', 'pdf_ocr')",
            name="ck_policy_document_versions_parser_type",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["policy_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_document_versions_document_status",
        "policy_document_versions",
        ["document_id", "publish_status"],
        unique=False,
    )
    op.create_index(
        "ix_policy_document_versions_content_hash",
        "policy_document_versions",
        ["content_hash"],
        unique=False,
    )
    op.create_index(
        "uq_one_published_version",
        "policy_document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("publish_status = 'published'"),
    )

    op.create_table(
        "document_elements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("element_type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("bbox_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "element_type in ('title', 'paragraph', 'table', 'figure', 'header', 'footer')",
            name="ck_document_elements_type",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["policy_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["policy_document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["document_elements.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_elements_version_order",
        "document_elements",
        ["version_id", "order_index"],
        unique=False,
    )
    op.create_index("ix_document_elements_document_id", "document_elements", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_elements_document_id", table_name="document_elements")
    op.drop_index("ix_document_elements_version_order", table_name="document_elements")
    op.drop_table("document_elements")

    op.drop_index("uq_one_published_version", table_name="policy_document_versions")
    op.drop_index("ix_policy_document_versions_content_hash", table_name="policy_document_versions")
    op.drop_index("ix_policy_document_versions_document_status", table_name="policy_document_versions")
    op.drop_table("policy_document_versions")

    op.drop_index("ix_policy_documents_effective_date", table_name="policy_documents")
    op.drop_index("ix_policy_documents_validity_status", table_name="policy_documents")
    op.drop_index("ix_policy_documents_policy_level", table_name="policy_documents")
    op.drop_index("ix_policy_documents_source_url", table_name="policy_documents")
    op.drop_table("policy_documents")

    op.drop_index("ix_source_files_parse_status", table_name="source_files")
    op.drop_index("ix_source_files_source_url", table_name="source_files")
    op.drop_index("ix_source_files_file_hash", table_name="source_files")
    op.drop_table("source_files")
