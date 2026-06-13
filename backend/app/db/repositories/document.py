from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.document import (
    DocumentElement,
    PolicyDocument,
    PolicyDocumentVersion,
    SourceFile,
)


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_document(self, document_id: UUID) -> PolicyDocument | None:
        return self.db.get(PolicyDocument, document_id)

    def get_document_by_source_file_id(self, source_file_id: UUID) -> PolicyDocument | None:
        return self.db.scalar(
            select(PolicyDocument)
            .where(PolicyDocument.source_file_id == source_file_id)
            .order_by(PolicyDocument.created_at.asc())
            .limit(1)
        )

    def create_document(
        self,
        *,
        source_file: SourceFile,
        title: str,
        topic: str | None = None,
    ) -> PolicyDocument:
        document = PolicyDocument(
            source_file_id=source_file.id,
            title=title,
            source_url=source_file.source_url,
            topic=topic,
        )
        self.db.add(document)
        self.db.flush()
        return document

    def get_version(self, version_id: UUID) -> PolicyDocumentVersion | None:
        return self.db.get(PolicyDocumentVersion, version_id)

    def get_version_by_document_hash(
        self,
        *,
        document_id: UUID,
        content_hash: str,
    ) -> PolicyDocumentVersion | None:
        return self.db.scalar(
            select(PolicyDocumentVersion).where(
                PolicyDocumentVersion.document_id == document_id,
                PolicyDocumentVersion.content_hash == content_hash,
            )
        )

    def next_version_no(self, *, document_id: UUID) -> str:
        count = self.db.scalar(
            select(func.count(PolicyDocumentVersion.id)).where(
                PolicyDocumentVersion.document_id == document_id,
            )
        )
        return f"v{(count or 0) + 1}"

    def create_version(
        self,
        *,
        document_id: UUID,
        version_no: str,
        raw_text: str,
        clean_text: str,
        markdown_text: str,
        parse_json: dict,
        content_hash: str,
        parser_type: str,
    ) -> PolicyDocumentVersion:
        version = PolicyDocumentVersion(
            document_id=document_id,
            version_no=version_no,
            raw_text=raw_text,
            clean_text=clean_text,
            markdown_text=markdown_text,
            parse_json=parse_json,
            content_hash=content_hash,
            parser_type=parser_type,
        )
        self.db.add(version)
        self.db.flush()
        return version

    def create_elements(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        elements: list[dict],
    ) -> list[DocumentElement]:
        created: list[DocumentElement] = []
        for element in elements:
            parent_index = element.pop("parent_index", None)
            created_element = DocumentElement(
                document_id=document_id,
                version_id=version_id,
                **element,
            )
            self.db.add(created_element)
            created.append(created_element)
            self.db.flush()
            if parent_index is not None:
                created_element.parent_id = created[parent_index].id

        self.db.flush()
        return created

    def list_elements(self, *, version_id: UUID) -> list[DocumentElement]:
        return list(
            self.db.scalars(
                select(DocumentElement)
                .where(DocumentElement.version_id == version_id)
                .order_by(DocumentElement.order_index.asc())
            )
        )
