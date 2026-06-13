from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.rag_chunk import RagChunk


class RagChunkRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_version(self, *, version_id: UUID) -> list[RagChunk]:
        return list(
            self.db.scalars(
                select(RagChunk)
                .where(RagChunk.version_id == version_id)
                .order_by(RagChunk.order_index.asc())
            )
        )

    def get_by_version_and_hash(self, *, version_id: UUID, content_hash: str) -> RagChunk | None:
        return self.db.scalar(
            select(RagChunk).where(
                RagChunk.version_id == version_id,
                RagChunk.content_hash == content_hash,
            )
        )

    def create_or_reuse_chunks(self, *, chunk_rows: list[dict]) -> tuple[list[RagChunk], int]:
        chunks: list[RagChunk] = []
        reused_count = 0
        for row in chunk_rows:
            existing = self.get_by_version_and_hash(
                version_id=row["version_id"],
                content_hash=row["content_hash"],
            )
            if existing is not None:
                chunks.append(existing)
                reused_count += 1
                continue

            chunk = RagChunk(**row)
            self.db.add(chunk)
            chunks.append(chunk)
            self.db.flush()

        for index, chunk in enumerate(chunks):
            chunk.prev_chunk_id = chunks[index - 1].id if index > 0 else None
            chunk.next_chunk_id = chunks[index + 1].id if index + 1 < len(chunks) else None
        self.db.flush()
        return chunks, reused_count
