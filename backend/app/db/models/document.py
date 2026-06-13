from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (
        CheckConstraint("file_type in ('pdf', 'html', 'csv', 'xlsx')", name="ck_source_files_type"),
        CheckConstraint(
            "parse_status in ('pending', 'parsed', 'partial', 'failed')",
            name="ck_source_files_parse_status",
        ),
        Index("ix_source_files_file_hash", "file_hash", unique=True),
        Index("ix_source_files_source_url", "source_url"),
        Index("ix_source_files_parse_status", "parse_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    __table_args__ = (
        CheckConstraint(
            "policy_level in ('national', 'province', 'city', 'district')",
            name="ck_policy_documents_policy_level",
        ),
        CheckConstraint(
            "validity_status in ('active', 'expired', 'abolished', 'unknown')",
            name="ck_policy_documents_validity_status",
        ),
        CheckConstraint("status in ('active', 'archived')", name="ck_policy_documents_status"),
        Index("ix_policy_documents_source_url", "source_url"),
        Index("ix_policy_documents_policy_level", "policy_level"),
        Index("ix_policy_documents_validity_status", "validity_status"),
        Index("ix_policy_documents_effective_date", "effective_date"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    issuing_agency: Mapped[str | None] = mapped_column(String(255))
    document_no: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(1024))
    publish_date: Mapped[date | None] = mapped_column(Date())
    topic: Mapped[str | None] = mapped_column(String(128))
    policy_level: Mapped[str] = mapped_column(String(16), nullable=False, default="city")
    effective_date: Mapped[date | None] = mapped_column(Date())
    expiry_date: Mapped[date | None] = mapped_column(Date())
    abolished_date: Mapped[date | None] = mapped_column(Date())
    validity_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    keywords_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PolicyDocumentVersion(Base):
    __tablename__ = "policy_document_versions"
    __table_args__ = (
        CheckConstraint(
            "publish_status in ('draft', 'published', 'archived')",
            name="ck_policy_document_versions_publish_status",
        ),
        CheckConstraint(
            "parser_type in ('html', 'pdf_text', 'pdf_ocr')",
            name="ck_policy_document_versions_parser_type",
        ),
        Index("ix_policy_document_versions_document_status", "document_id", "publish_status"),
        Index("ix_policy_document_versions_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    clean_text: Mapped[str | None] = mapped_column(Text)
    markdown_text: Mapped[str | None] = mapped_column(Text)
    parse_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    publish_status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    parser_type: Mapped[str] = mapped_column(String(16), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class DocumentElement(Base):
    __tablename__ = "document_elements"
    __table_args__ = (
        CheckConstraint(
            "element_type in ('title', 'paragraph', 'table', 'figure', 'header', 'footer')",
            name="ck_document_elements_type",
        ),
        Index("ix_document_elements_version_order", "version_id", "order_index"),
        Index("ix_document_elements_document_id", "document_id"),
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
    element_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_no: Mapped[int | None] = mapped_column()
    order_index: Mapped[int] = mapped_column(nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_elements.id", ondelete="SET NULL"),
    )
    heading_level: Mapped[int | None] = mapped_column()
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
