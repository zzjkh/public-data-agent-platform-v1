from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models.document import SourceFile


class SourceFileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, source_file_id: UUID) -> SourceFile | None:
        return self.db.get(SourceFile, source_file_id)

    def get_by_hash(self, file_hash: str) -> SourceFile | None:
        return self.db.scalar(select(SourceFile).where(SourceFile.file_hash == file_hash))

    def create(
        self,
        *,
        file_name: str,
        file_type: str,
        storage_uri: str,
        source_url: str | None,
        file_hash: str,
        file_version: str,
        uploaded_by: UUID | None,
    ) -> SourceFile:
        source_file = SourceFile(
            file_name=file_name,
            file_type=file_type,
            storage_uri=storage_uri,
            source_url=source_url,
            file_hash=file_hash,
            file_version=file_version,
            uploaded_by=uploaded_by,
        )
        self.db.add(source_file)
        self.db.flush()
        return source_file

    def list(
        self,
        *,
        page: int,
        page_size: int,
        parse_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SourceFile], int]:
        statement = select(SourceFile)
        statement = self._apply_filters(statement, parse_status=parse_status, keyword=keyword)

        count_statement = select(func.count(SourceFile.id))
        if parse_status:
            count_statement = count_statement.where(SourceFile.parse_status == parse_status)
        if keyword:
            like_keyword = f"%{keyword}%"
            count_statement = count_statement.where(SourceFile.file_name.ilike(like_keyword))
        total = self.db.scalar(count_statement) or 0

        items = list(
            self.db.scalars(
                statement.order_by(SourceFile.uploaded_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def _apply_filters(
        self,
        statement: Select[tuple[SourceFile]],
        *,
        parse_status: str | None,
        keyword: str | None,
    ) -> Select[tuple[SourceFile]]:
        if parse_status:
            statement = statement.where(SourceFile.parse_status == parse_status)
        if keyword:
            statement = statement.where(SourceFile.file_name.ilike(f"%{keyword}%"))
        return statement
