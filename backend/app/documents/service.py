from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.document import DocumentElement, PolicyDocumentVersion, SourceFile
from app.db.models.rag_chunk import RagChunk
from app.db.repositories.chunk_embedding import ChunkEmbeddingRepository
from app.db.repositories.document import DocumentRepository
from app.db.repositories.rag_chunk import RagChunkRepository
from app.db.repositories.source_file import SourceFileRepository
from app.files.storage import LocalFileStorage
from app.ingestion.parsers.html_parser import ParsedHtmlDocument, parse_html_document
from app.ingestion.parsers.ocr_engine import OcrEngine
from app.ingestion.parsers.pdf_ocr_parser import ParsedOcrDocument, parse_pdf_ocr_document
from app.ingestion.parsers.pdf_text_parser import ParsedPdfDocument, parse_pdf_text_document


class DocumentParseError(ValueError):
    pass


class DocumentPublishError(ValueError):
    pass


class DocumentService:
    def __init__(self, db: Session, storage: LocalFileStorage) -> None:
        self.db = db
        self.storage = storage
        self.source_files = SourceFileRepository(db)
        self.documents = DocumentRepository(db)
        self.chunks = RagChunkRepository(db)
        self.embeddings = ChunkEmbeddingRepository(db)

    def parse_html_source_file(
        self,
        *,
        source_file_id: UUID,
        document_id: UUID | None = None,
    ) -> tuple[PolicyDocumentVersion, list[DocumentElement], bool]:
        source_file = self.source_files.get_by_id(source_file_id)
        if source_file is None:
            raise DocumentParseError("Source file not found")
        if source_file.file_type != "html":
            raise DocumentParseError(f"HTML parser cannot parse file_type={source_file.file_type}")

        html = read_text_file(self.storage.resolve(source_file.storage_uri))
        parsed = parse_html_document(html, fallback_title=source_file.file_name)
        if not parsed.clean_text:
            source_file.parse_status = "failed"
            source_file.error_message = "HTML parser produced empty clean_text"
            raise DocumentParseError(source_file.error_message)

        return self._persist_parsed_document(
            source_file=source_file,
            document_id=document_id,
            title=parsed.title,
            raw_text=parsed.raw_text,
            clean_text=parsed.clean_text,
            markdown_text=parsed.markdown_text,
            parse_json={
                "parser_type": "html",
                "extraction_mode": parsed.extraction_mode,
                "source_file_id": str(source_file.id),
                "source_url": source_file.source_url,
                "title": parsed.title,
                "element_count": len(parsed.elements),
            },
            parser_type="html",
            element_rows=html_element_rows(parsed),
        )

    def parse_pdf_text_source_file(
        self,
        *,
        source_file_id: UUID,
        document_id: UUID | None = None,
        table_extraction_enabled: bool = True,
        agent_refine_enabled: bool = False,
    ) -> tuple[PolicyDocumentVersion, list[DocumentElement], bool]:
        source_file = self.source_files.get_by_id(source_file_id)
        if source_file is None:
            raise DocumentParseError("Source file not found")
        if source_file.file_type != "pdf":
            raise DocumentParseError(f"PDF text parser cannot parse file_type={source_file.file_type}")

        parsed = parse_pdf_text_document(
            self.storage.resolve(source_file.storage_uri),
            fallback_title=source_file.file_name,
            table_extraction_enabled=table_extraction_enabled,
            agent_refine_enabled=agent_refine_enabled,
        )
        if not parsed.clean_text:
            source_file.parse_status = "failed"
            source_file.error_message = "PDF text parser produced empty clean_text"
            raise DocumentParseError(source_file.error_message)

        return self._persist_parsed_document(
            source_file=source_file,
            document_id=document_id,
            title=parsed.title,
            raw_text=parsed.raw_text,
            clean_text=parsed.clean_text,
            markdown_text=parsed.markdown_text,
            parse_json={
                "parser_type": "pdf_text",
                "extractor_mode": "layout",
                "agent_refine_enabled": parsed.agent_refine_enabled,
                "table_extraction_errors": parsed.table_extraction_errors,
                "source_file_id": str(source_file.id),
                "source_url": source_file.source_url,
                "title": parsed.title,
                "page_count": parsed.page_count,
                "element_count": len(parsed.elements),
            },
            parser_type="pdf_text",
            element_rows=pdf_element_rows(parsed),
        )

    def parse_pdf_ocr_source_file(
        self,
        *,
        source_file_id: UUID,
        ocr_engine: OcrEngine,
        document_id: UUID | None = None,
        lang: str = "ch",
        render_dpi: int = 180,
        min_text_length: int = 20,
        agent_refine_enabled: bool = False,
    ) -> tuple[PolicyDocumentVersion, list[DocumentElement], bool]:
        source_file = self.source_files.get_by_id(source_file_id)
        if source_file is None:
            raise DocumentParseError("Source file not found")
        if source_file.file_type != "pdf":
            raise DocumentParseError(f"PDF OCR parser cannot parse file_type={source_file.file_type}")

        try:
            parsed = parse_pdf_ocr_document(
                self.storage.resolve(source_file.storage_uri),
                fallback_title=source_file.file_name,
                ocr_engine=ocr_engine,
                lang=lang,
                render_dpi=render_dpi,
                agent_refine_enabled=agent_refine_enabled,
            )
        except Exception as exc:
            source_file.parse_status = "failed"
            source_file.error_message = f"OCR parser failed: {exc}"
            self.db.flush()
            raise DocumentParseError(source_file.error_message) from exc

        if len(parsed.clean_text) < min_text_length:
            source_file.parse_status = "failed"
            source_file.error_message = (
                f"OCR parser produced too little text: {len(parsed.clean_text)} chars"
            )
            raise DocumentParseError(source_file.error_message)

        return self._persist_parsed_document(
            source_file=source_file,
            document_id=document_id,
            title=parsed.title,
            raw_text=parsed.raw_text,
            clean_text=parsed.clean_text,
            markdown_text=parsed.markdown_text,
            parse_json={
                "parser_type": "pdf_ocr",
                "ocr_engine": parsed.ocr_engine,
                "ocr_lang": lang,
                "render_dpi": parsed.render_dpi,
                "agent_refine_enabled": parsed.agent_refine_enabled,
                "source_file_id": str(source_file.id),
                "source_url": source_file.source_url,
                "title": parsed.title,
                "page_count": parsed.page_count,
                "element_count": len(parsed.elements),
            },
            parser_type="pdf_ocr",
            element_rows=ocr_element_rows(parsed),
        )

    def _persist_parsed_document(
        self,
        *,
        source_file: SourceFile,
        document_id: UUID | None,
        title: str,
        raw_text: str,
        clean_text: str,
        markdown_text: str,
        parse_json: dict,
        parser_type: str,
        element_rows: list[dict],
    ) -> tuple[PolicyDocumentVersion, list[DocumentElement], bool]:
        if document_id is not None:
            document = self.documents.get_document(document_id)
            if document is None:
                raise DocumentParseError("Policy document not found")
        else:
            document = self.documents.get_document_by_source_file_id(source_file.id)
            if document is None:
                document = self.documents.create_document(source_file=source_file, title=title)

        content_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
        existing = self.documents.get_version_by_document_hash(
            document_id=document.id,
            content_hash=content_hash,
        )
        if existing is not None:
            elements = self.documents.list_elements(version_id=existing.id)
            source_file.parse_status = "parsed"
            source_file.error_message = None
            self.db.flush()
            return existing, elements, True

        version = self.documents.create_version(
            document_id=document.id,
            version_no=self.documents.next_version_no(document_id=document.id),
            raw_text=raw_text,
            clean_text=clean_text,
            markdown_text=markdown_text,
            parse_json=parse_json,
            content_hash=content_hash,
            parser_type=parser_type,
        )
        elements = self.documents.create_elements(
            document_id=document.id,
            version_id=version.id,
            elements=element_rows,
        )
        source_file.parse_status = "parsed"
        source_file.error_message = None
        self.db.flush()
        return version, elements, False

    def list_elements(self, *, version_id: UUID) -> list[DocumentElement]:
        version = self.documents.get_version(version_id)
        if version is None:
            raise DocumentParseError("Policy document version not found")
        return self.documents.list_elements(version_id=version_id)

    def list_chunks(self, *, version_id: UUID) -> list[RagChunk]:
        version = self.documents.get_version(version_id)
        if version is None:
            raise DocumentParseError("Policy document version not found")
        return self.chunks.list_by_version(version_id=version_id)

    def publish_version(
        self,
        *,
        version_id: UUID,
        embedding_model: str,
        embedding_version: str,
        metadata: dict,
    ) -> tuple[PolicyDocumentVersion, list[UUID]]:
        version = self.documents.get_version(version_id)
        if version is None:
            raise DocumentPublishError("Policy document version not found")
        document = self.documents.get_document(version.document_id)
        if document is None:
            raise DocumentPublishError("Policy document not found")

        chunks = self.chunks.list_by_version(version_id=version.id)
        if not chunks:
            raise DocumentPublishError("Cannot publish before rag_chunks exist")
        chunk_ids = [chunk.id for chunk in chunks]
        embedded_chunk_ids = self.embeddings.get_existing_chunk_ids(
            chunk_ids=chunk_ids,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )
        if len(embedded_chunk_ids) != len(chunk_ids):
            raise DocumentPublishError(
                "Cannot publish before all chunks have embeddings for the configured model/version"
            )

        archived_versions = list(
            self.db.scalars(
                select(PolicyDocumentVersion).where(
                    PolicyDocumentVersion.document_id == document.id,
                    PolicyDocumentVersion.id != version.id,
                    PolicyDocumentVersion.publish_status == "published",
                )
            )
        )
        for archived in archived_versions:
            archived.publish_status = "archived"
        if archived_versions:
            self.db.flush()

        for field in (
            "title",
            "issuing_agency",
            "document_no",
            "publish_date",
            "topic",
            "policy_level",
            "validity_status",
        ):
            value = metadata.get(field)
            if value is not None:
                setattr(document, field, value)
        if metadata.get("keywords") is not None:
            document.keywords_json = {"keywords": list(metadata["keywords"])}

        version.publish_status = "published"
        version.published_at = version.published_at or datetime.now(UTC)
        self.db.commit()
        self.db.refresh(version)
        return version, [archived.id for archived in archived_versions]


def html_element_rows(parsed: ParsedHtmlDocument) -> list[dict]:
    return [
        {
            "element_type": element.element_type,
            "content": element.content,
            "page_no": None,
            "order_index": element.order_index,
            "parent_index": element.parent_index,
            "heading_level": element.heading_level,
            "bbox_json": None,
            "metadata_json": element.metadata or {},
        }
        for element in parsed.elements
    ]


def pdf_element_rows(parsed: ParsedPdfDocument) -> list[dict]:
    return [
        {
            "element_type": element.element_type,
            "content": element.content,
            "page_no": element.page_no,
            "order_index": element.order_index,
            "parent_index": element.parent_index,
            "heading_level": element.heading_level,
            "bbox_json": element.bbox,
            "metadata_json": element.metadata or {},
        }
        for element in parsed.elements
    ]


def ocr_element_rows(parsed: ParsedOcrDocument) -> list[dict]:
    return [
        {
            "element_type": element.element_type,
            "content": element.content,
            "page_no": element.page_no,
            "order_index": element.order_index,
            "parent_index": element.parent_index,
            "heading_level": element.heading_level,
            "bbox_json": element.bbox,
            "metadata_json": element.metadata or {},
        }
        for element in parsed.elements
    ]


def read_text_file(path: Path) -> str:
    content = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")
