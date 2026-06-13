from __future__ import annotations

from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.db.models.document import SourceFile
from app.db.repositories.source_file import SourceFileRepository
from app.files.storage import LocalFileStorage, StoredFile


class SourceFileService:
    def __init__(self, db: Session, storage: LocalFileStorage) -> None:
        self.db = db
        self.storage = storage
        self.repository = SourceFileRepository(db)

    def upload(
        self,
        *,
        upload_file: UploadFile,
        source_url: str | None,
        file_version: str,
        uploaded_by: UUID | None,
    ) -> SourceFile:
        stored = self.storage.save_upload(upload_file)
        existing = self.repository.get_by_hash(stored.file_hash)
        if existing is not None:
            return existing

        source_file = self._create_source_file(
            stored=stored,
            source_url=source_url,
            file_version=file_version,
            uploaded_by=uploaded_by,
        )
        self.db.commit()
        self.db.refresh(source_file)
        return source_file

    def list(
        self,
        *,
        page: int,
        page_size: int,
        parse_status: str | None,
        keyword: str | None,
    ) -> tuple[list[SourceFile], int]:
        return self.repository.list(
            page=page,
            page_size=page_size,
            parse_status=parse_status,
            keyword=keyword,
        )

    def _create_source_file(
        self,
        *,
        stored: StoredFile,
        source_url: str | None,
        file_version: str,
        uploaded_by: UUID | None,
    ) -> SourceFile:
        return self.repository.create(
            file_name=stored.file_name,
            file_type=stored.file_type,
            storage_uri=stored.storage_uri,
            source_url=source_url,
            file_hash=stored.file_hash,
            file_version=file_version,
            uploaded_by=uploaded_by,
        )
