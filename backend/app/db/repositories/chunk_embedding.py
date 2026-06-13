from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models.rag_chunk import ChunkEmbedding


class ChunkEmbeddingRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_chunk_ids(
        self,
        *,
        chunk_ids: list[UUID],
        embedding_model: str,
        embedding_version: str,
    ) -> list[ChunkEmbedding]:
        if not chunk_ids:
            return []
        return list(
            self.db.scalars(
                select(ChunkEmbedding).where(
                    ChunkEmbedding.chunk_id.in_(chunk_ids),
                    ChunkEmbedding.embedding_model == embedding_model,
                    ChunkEmbedding.embedding_version == embedding_version,
                )
            )
        )

    def get_existing_chunk_ids(
        self,
        *,
        chunk_ids: list[UUID],
        embedding_model: str,
        embedding_version: str,
    ) -> set[UUID]:
        embeddings = self.list_by_chunk_ids(
            chunk_ids=chunk_ids,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )
        return {embedding.chunk_id for embedding in embeddings}

    def create_embeddings(self, *, rows: list[dict]) -> list[ChunkEmbedding]:
        created: list[ChunkEmbedding] = []
        if not rows:
            return created

        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            for row in rows:
                embedding_id = uuid4()
                self.db.execute(
                    text(
                        """
                        INSERT INTO chunk_embeddings (
                            id,
                            chunk_id,
                            embedding_model,
                            embedding_dim,
                            embedding_version,
                            embedding
                        )
                        VALUES (
                            :id,
                            :chunk_id,
                            :embedding_model,
                            :embedding_dim,
                            :embedding_version,
                            CAST(:embedding AS vector)
                        )
                        """
                    ),
                    {
                        "id": embedding_id,
                        "chunk_id": row["chunk_id"],
                        "embedding_model": row["embedding_model"],
                        "embedding_dim": row["embedding_dim"],
                        "embedding_version": row["embedding_version"],
                        "embedding": vector_to_pg_literal(row["embedding"]),
                    },
                )
                created_embedding = self.db.get(ChunkEmbedding, embedding_id)
                if created_embedding is not None:
                    created.append(created_embedding)
        else:
            for row in rows:
                embedding = ChunkEmbedding(**row)
                self.db.add(embedding)
                created.append(embedding)
            self.db.flush()
        return created


def vector_to_pg_literal(vector: list[float]) -> str:
    values = ",".join(format(float(value), ".10g") for value in vector)
    return f"[{values}]"
