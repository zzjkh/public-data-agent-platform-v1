from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import bindparam, or_, select, text
from sqlalchemy.orm import Session

from app.db.models.semantic_metadata import SemanticMetadataEmbedding, SemanticMetadataItem
from app.db.repositories.chunk_embedding import vector_to_pg_literal
from app.llm.embedding_provider import EmbeddingProvider
from app.rag.retriever import (
    cosine_similarity,
    escape_like,
    extract_query_terms,
    keyword_scores,
    normalize_query,
)
from app.semantic.service import normalize_metadata_types


DEFAULT_SEMANTIC_TOP_K = 8
DEFAULT_DENSE_TOP_K = 20
DEFAULT_KEYWORD_TOP_K = 20


class SemanticRetrievalError(ValueError):
    pass


@dataclass
class RetrievedSemanticMetadata:
    item: SemanticMetadataItem
    dense_score: float = 0.0
    keyword_score: float = 0.0
    fulltext_score: float = 0.0
    exact_score: float = 0.0
    final_score: float = 0.0
    match_sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticRetrievalResult:
    query: str
    items: list[RetrievedSemanticMetadata]


class SemanticMetadataRetriever:
    def __init__(self, db: Session) -> None:
        self.db = db

    def retrieve(
        self,
        *,
        query: str,
        embedding_provider: EmbeddingProvider,
        embedding_model: str,
        embedding_version: str,
        metadata_types: list[str] | None = None,
        top_k: int = DEFAULT_SEMANTIC_TOP_K,
        dense_top_k: int = DEFAULT_DENSE_TOP_K,
        keyword_top_k: int = DEFAULT_KEYWORD_TOP_K,
    ) -> SemanticRetrievalResult:
        query = normalize_query(query)
        if not query:
            raise SemanticRetrievalError("query must not be empty")
        if top_k <= 0 or dense_top_k <= 0 or keyword_top_k <= 0:
            raise SemanticRetrievalError("top_k, dense_top_k and keyword_top_k must be positive")

        selected_types = normalize_metadata_types(metadata_types) if metadata_types else None
        query_vector = embedding_provider.embed_query(query)
        if len(query_vector) != embedding_provider.embedding_dim:
            raise SemanticRetrievalError(
                f"Query embedding dim mismatch: expected {embedding_provider.embedding_dim}, "
                f"got {len(query_vector)}"
            )

        candidates: dict[UUID, RetrievedSemanticMetadata] = {}
        for candidate in self._dense_retrieve(
            query_vector=query_vector,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            metadata_types=selected_types,
            limit=dense_top_k,
        ):
            merge_candidate(candidates, candidate, source="dense")

        for candidate in self._keyword_retrieve(
            query=query,
            metadata_types=selected_types,
            limit=keyword_top_k,
        ):
            merge_candidate(candidates, candidate, source="keyword")

        for candidate in self._fulltext_retrieve(
            query=query,
            metadata_types=selected_types,
            limit=keyword_top_k,
        ):
            merge_candidate(candidates, candidate, source="fulltext")

        ranked = rerank_candidates(list(candidates.values()))
        return SemanticRetrievalResult(query=query, items=ranked[:top_k])

    def _dense_retrieve(
        self,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_version: str,
        metadata_types: list[str] | None,
        limit: int,
    ) -> list[RetrievedSemanticMetadata]:
        if self._dialect_name == "postgresql":
            return self._dense_retrieve_postgres(
                query_vector=query_vector,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
                metadata_types=metadata_types,
                limit=limit,
            )
        return self._dense_retrieve_python(
            query_vector=query_vector,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            metadata_types=metadata_types,
            limit=limit,
        )

    def _dense_retrieve_python(
        self,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_version: str,
        metadata_types: list[str] | None,
        limit: int,
    ) -> list[RetrievedSemanticMetadata]:
        statement = (
            select(SemanticMetadataItem, SemanticMetadataEmbedding)
            .join(
                SemanticMetadataEmbedding,
                SemanticMetadataEmbedding.metadata_item_id == SemanticMetadataItem.id,
            )
            .where(
                SemanticMetadataEmbedding.embedding_model == embedding_model,
                SemanticMetadataEmbedding.embedding_version == embedding_version,
            )
        )
        statement = apply_metadata_type_filter(statement, metadata_types)
        candidates = []
        for item, embedding in self.db.execute(statement).all():
            vector = [float(value) for value in embedding.embedding]
            candidates.append(
                RetrievedSemanticMetadata(
                    item=item,
                    dense_score=cosine_similarity(query_vector, vector),
                )
            )
        candidates.sort(key=lambda candidate: candidate.dense_score, reverse=True)
        return candidates[:limit]

    def _dense_retrieve_postgres(
        self,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_version: str,
        metadata_types: list[str] | None,
        limit: int,
    ) -> list[RetrievedSemanticMetadata]:
        where_sql, params = postgres_metadata_type_where(metadata_types)
        statement = text(
            f"""
            SELECT
                i.id AS item_id,
                1 - (e.embedding <=> CAST(:query_vector AS vector)) AS dense_score
            FROM semantic_metadata_embeddings e
            JOIN semantic_metadata_items i ON i.id = e.metadata_item_id
            WHERE e.embedding_model = :embedding_model
              AND e.embedding_version = :embedding_version
              {where_sql}
            ORDER BY e.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        )
        if metadata_types:
            statement = statement.bindparams(bindparam("metadata_types", expanding=True))
        rows = self.db.execute(
            statement,
            {
                **params,
                "query_vector": vector_to_pg_literal(query_vector),
                "embedding_model": embedding_model,
                "embedding_version": embedding_version,
                "limit": limit,
            },
        ).mappings()
        candidates = []
        for row in rows:
            item = self.db.get(SemanticMetadataItem, row["item_id"])
            if item is not None:
                candidates.append(
                    RetrievedSemanticMetadata(
                        item=item,
                        dense_score=float(row["dense_score"] or 0.0),
                    )
                )
        return candidates

    def _keyword_retrieve(
        self,
        *,
        query: str,
        metadata_types: list[str] | None,
        limit: int,
    ) -> list[RetrievedSemanticMetadata]:
        terms = extract_query_terms(query)
        if not terms:
            return []
        statement = select(SemanticMetadataItem)
        statement = apply_metadata_type_filter(statement, metadata_types)
        clauses = []
        for term in [query, *terms[:16]]:
            like_pattern = f"%{escape_like(term)}%"
            clauses.extend(
                [
                    SemanticMetadataItem.name.ilike(like_pattern, escape="\\"),
                    SemanticMetadataItem.description.ilike(like_pattern, escape="\\"),
                    SemanticMetadataItem.search_text.ilike(like_pattern, escape="\\"),
                    SemanticMetadataItem.related_table.ilike(like_pattern, escape="\\"),
                    SemanticMetadataItem.related_field.ilike(like_pattern, escape="\\"),
                ]
            )
        rows = self.db.scalars(statement.where(or_(*clauses))).all()
        candidates = []
        for item in rows:
            keyword_score, exact_score = keyword_scores(
                query=query,
                terms=terms,
                text="\n".join([item.name, item.search_text, item.related_table, item.related_field]),
            )
            if keyword_score <= 0 and exact_score <= 0:
                continue
            candidates.append(
                RetrievedSemanticMetadata(
                    item=item,
                    keyword_score=keyword_score,
                    exact_score=exact_score,
                )
            )
        candidates.sort(
            key=lambda candidate: (candidate.exact_score, candidate.keyword_score),
            reverse=True,
        )
        return candidates[:limit]

    def _fulltext_retrieve(
        self,
        *,
        query: str,
        metadata_types: list[str] | None,
        limit: int,
    ) -> list[RetrievedSemanticMetadata]:
        if self._dialect_name != "postgresql":
            return []
        where_sql, params = postgres_metadata_type_where(metadata_types)
        statement = text(
            f"""
            SELECT
                i.id AS item_id,
                ts_rank(i.search_tsv, plainto_tsquery('simple', :query)) AS fulltext_score
            FROM semantic_metadata_items i
            WHERE i.search_tsv @@ plainto_tsquery('simple', :query)
              {where_sql}
            ORDER BY fulltext_score DESC
            LIMIT :limit
            """
        )
        if metadata_types:
            statement = statement.bindparams(bindparam("metadata_types", expanding=True))
        rows = self.db.execute(statement, {**params, "query": query, "limit": limit}).mappings()
        candidates = []
        for row in rows:
            item = self.db.get(SemanticMetadataItem, row["item_id"])
            if item is not None:
                candidates.append(
                    RetrievedSemanticMetadata(
                        item=item,
                        fulltext_score=float(row["fulltext_score"] or 0.0),
                    )
                )
        return candidates

    @property
    def _dialect_name(self) -> str:
        if self.db.bind is None:
            return ""
        return self.db.bind.dialect.name


def apply_metadata_type_filter(statement, metadata_types: list[str] | None):
    if metadata_types:
        statement = statement.where(SemanticMetadataItem.metadata_type.in_(metadata_types))
    return statement


def postgres_metadata_type_where(metadata_types: list[str] | None) -> tuple[str, dict]:
    if not metadata_types:
        return "", {}
    return "AND i.metadata_type IN :metadata_types", {"metadata_types": metadata_types}


def merge_candidate(
    candidates: dict[UUID, RetrievedSemanticMetadata],
    candidate: RetrievedSemanticMetadata,
    *,
    source: str,
) -> None:
    existing = candidates.get(candidate.item.id)
    if existing is None:
        candidate.match_sources = [source]
        candidates[candidate.item.id] = candidate
        return

    existing.dense_score = max(existing.dense_score, candidate.dense_score)
    existing.keyword_score = max(existing.keyword_score, candidate.keyword_score)
    existing.fulltext_score = max(existing.fulltext_score, candidate.fulltext_score)
    existing.exact_score = max(existing.exact_score, candidate.exact_score)
    if source not in existing.match_sources:
        existing.match_sources.append(source)


def rerank_candidates(candidates: list[RetrievedSemanticMetadata]) -> list[RetrievedSemanticMetadata]:
    for candidate in candidates:
        candidate.final_score = (
            candidate.dense_score * 0.68
            + candidate.keyword_score * 0.18
            + candidate.fulltext_score * 0.08
            + candidate.exact_score * 0.24
            + metadata_type_boost(candidate.item.metadata_type)
        )
    return sorted(candidates, key=lambda candidate: candidate.final_score, reverse=True)


def metadata_type_boost(metadata_type: str) -> float:
    if metadata_type in {"metric", "table", "field"}:
        return 0.04
    if metadata_type == "sql_example":
        return 0.03
    if metadata_type == "business_rule":
        return 0.02
    return 0.0
