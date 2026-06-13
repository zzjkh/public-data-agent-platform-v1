from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.rag_chunk import ChunkEmbedding, RagChunk
from app.db.repositories.chunk_embedding import ChunkEmbeddingRepository
from app.db.repositories.document import DocumentRepository
from app.db.repositories.rag_chunk import RagChunkRepository
from app.llm.embedding_provider import EmbeddingProvider


class EmbeddingBuildError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkEmbeddingBuildResult:
    version_id: UUID
    document_id: UUID
    embeddings: list[ChunkEmbedding]
    chunk_count: int
    created_count: int
    reused_count: int
    embedding_model: str
    embedding_dim: int
    embedding_version: str


class ChunkEmbeddingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.documents = DocumentRepository(db)
        self.chunks = RagChunkRepository(db)
        self.embeddings = ChunkEmbeddingRepository(db)

    def build_embeddings(
        self,
        *,
        version_id: UUID,
        provider: EmbeddingProvider,
        embedding_model: str,
        embedding_dim: int,
        embedding_version: str,
        batch_size: int,
        max_retries: int,
    ) -> ChunkEmbeddingBuildResult:
        validate_embedding_options(batch_size=batch_size, max_retries=max_retries)
        version = self.documents.get_version(version_id)
        if version is None:
            raise EmbeddingBuildError("Policy document version not found")
        chunks = self.chunks.list_by_version(version_id=version_id)
        if not chunks:
            raise EmbeddingBuildError("Cannot build embeddings before rag_chunks exist")

        if provider.embedding_dim != embedding_dim:
            raise EmbeddingBuildError(
                f"Provider dim mismatch: settings={embedding_dim}, provider={provider.embedding_dim}"
            )

        chunk_ids = [chunk.id for chunk in chunks]
        existing_chunk_ids = self.embeddings.get_existing_chunk_ids(
            chunk_ids=chunk_ids,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )
        pending_chunks = [chunk for chunk in chunks if chunk.id not in existing_chunk_ids]
        created_embeddings: list[ChunkEmbedding] = []

        for batch in batched(pending_chunks, batch_size):
            vectors = embed_with_retries(
                provider=provider,
                texts=[chunk.embedding_text for chunk in batch],
                max_retries=max_retries,
            )
            rows = [
                embedding_row(
                    chunk=chunk,
                    vector=vector,
                    embedding_model=embedding_model,
                    embedding_dim=embedding_dim,
                    embedding_version=embedding_version,
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            created_embeddings.extend(self.embeddings.create_embeddings(rows=rows))

        self.db.flush()
        return ChunkEmbeddingBuildResult(
            version_id=version.id,
            document_id=version.document_id,
            embeddings=created_embeddings,
            chunk_count=len(chunks),
            created_count=len(created_embeddings),
            reused_count=len(existing_chunk_ids),
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            embedding_version=embedding_version,
        )


def embed_with_retries(
    *,
    provider: EmbeddingProvider,
    texts: list[str],
    max_retries: int,
) -> list[list[float]]:
    attempts = max_retries + 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            vectors = provider.embed_documents(texts)
            validate_vectors(vectors=vectors, expected_count=len(texts), expected_dim=provider.embedding_dim)
            return vectors
        except Exception as exc:
            last_error = exc
    raise EmbeddingBuildError(f"Embedding provider failed after {attempts} attempts: {last_error}")


def validate_vectors(
    *,
    vectors: list[list[float]],
    expected_count: int,
    expected_dim: int,
) -> None:
    if len(vectors) != expected_count:
        raise EmbeddingBuildError(
            f"Embedding count mismatch: expected {expected_count}, got {len(vectors)}"
        )
    for vector in vectors:
        if len(vector) != expected_dim:
            raise EmbeddingBuildError(
                f"Embedding dim mismatch: expected {expected_dim}, got {len(vector)}"
            )


def embedding_row(
    *,
    chunk: RagChunk,
    vector: list[float],
    embedding_model: str,
    embedding_dim: int,
    embedding_version: str,
) -> dict:
    return {
        "chunk_id": chunk.id,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "embedding_version": embedding_version,
        "embedding": [float(value) for value in vector],
    }


def batched(chunks: list[RagChunk], batch_size: int) -> list[list[RagChunk]]:
    return [chunks[index : index + batch_size] for index in range(0, len(chunks), batch_size)]


def validate_embedding_options(*, batch_size: int, max_retries: int) -> None:
    if batch_size <= 0:
        raise EmbeddingBuildError("embedding batch_size must be positive")
    if max_retries < 0:
        raise EmbeddingBuildError("embedding max_retries must not be negative")
