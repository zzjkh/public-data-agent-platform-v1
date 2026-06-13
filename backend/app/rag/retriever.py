from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, case, or_, select, text
from sqlalchemy.orm import Session

from app.db.models.document import PolicyDocument, PolicyDocumentVersion
from app.db.models.rag_chunk import ChunkEmbedding, RagChunk
from app.db.repositories.chunk_embedding import vector_to_pg_literal
from app.llm.embedding_provider import EmbeddingProvider


DEFAULT_TOP_K = 8
DEFAULT_DENSE_TOP_K = 20
DEFAULT_KEYWORD_TOP_K = 20
DEFAULT_VALIDITY_STATUSES = ("active", "unknown")
MAX_QUERY_TERMS = 64
MAX_KEYWORD_PREFILTER_TERMS = 16
KEYWORD_PREFILTER_MULTIPLIER = 10
MIN_KEYWORD_PREFILTER_LIMIT = 100
MAX_KEYWORD_PREFILTER_LIMIT = 500
MAX_CHUNKS_PER_DOCUMENT = 2
CHINESE_STOP_TERMS = {
    "什么",
    "哪些",
    "如何",
    "怎么",
    "怎样",
    "是否",
    "可以",
    "需要",
    "关于",
    "有关",
}


class PolicyRetrievalError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyRetrievalFilters:
    published_only: bool = True
    validity_statuses: tuple[str, ...] = DEFAULT_VALIDITY_STATUSES
    policy_levels: tuple[str, ...] | None = None
    publish_date_from: date | None = None
    publish_date_to: date | None = None
    effective_date_from: date | None = None
    effective_date_to: date | None = None


@dataclass
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    chunk_text: str
    heading_path: str | None
    element_ids: list[str]
    order_index: int
    document_title: str
    issuing_agency: str | None
    document_no: str | None
    source_url: str | None
    publish_date: date | None
    policy_level: str
    validity_status: str
    publish_status: str
    dense_score: float = 0.0
    keyword_score: float = 0.0
    fulltext_score: float = 0.0
    exact_score: float = 0.0
    metadata_score: float = 0.0
    final_score: float = 0.0
    match_sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyRetrievalResult:
    query: str
    chunks: list[RetrievedChunk]
    filters: PolicyRetrievalFilters


class PolicyRetriever:
    def __init__(self, db: Session) -> None:
        self.db = db

    def retrieve(
        self,
        *,
        query: str,
        embedding_provider: EmbeddingProvider,
        embedding_model: str,
        embedding_version: str,
        filters: PolicyRetrievalFilters | None = None,
        top_k: int = DEFAULT_TOP_K,
        dense_top_k: int = DEFAULT_DENSE_TOP_K,
        keyword_top_k: int = DEFAULT_KEYWORD_TOP_K,
    ) -> PolicyRetrievalResult:
        query = normalize_query(query)
        if not query:
            raise PolicyRetrievalError("query must not be empty")
        if top_k <= 0 or dense_top_k <= 0 or keyword_top_k <= 0:
            raise PolicyRetrievalError("top_k, dense_top_k and keyword_top_k must be positive")

        filters = filters or PolicyRetrievalFilters()
        query_vector = embedding_provider.embed_query(query)
        if len(query_vector) != embedding_provider.embedding_dim:
            raise PolicyRetrievalError(
                f"Query embedding dim mismatch: expected {embedding_provider.embedding_dim}, "
                f"got {len(query_vector)}"
            )

        candidates: dict[UUID, RetrievedChunk] = {}
        for candidate in self._dense_retrieve(
            query_vector=query_vector,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            filters=filters,
            limit=dense_top_k,
        ):
            merge_candidate(candidates, candidate, source="dense")

        for candidate in self._keyword_retrieve(query=query, filters=filters, limit=keyword_top_k):
            merge_candidate(candidates, candidate, source="keyword")

        for candidate in self._fulltext_retrieve(query=query, filters=filters, limit=keyword_top_k):
            merge_candidate(candidates, candidate, source="fulltext")

        ranked = rerank_candidates(
            candidates=list(candidates.values()),
            query=query,
            filters=filters,
        )
        return PolicyRetrievalResult(
            query=query,
            chunks=limit_chunks_per_document(ranked, top_k=top_k),
            filters=filters,
        )

    def _dense_retrieve(
        self,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_version: str,
        filters: PolicyRetrievalFilters,
        limit: int,
    ) -> list[RetrievedChunk]:
        if self._dialect_name == "postgresql":
            return self._dense_retrieve_postgres(
                query_vector=query_vector,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
                filters=filters,
                limit=limit,
            )
        return self._dense_retrieve_python(
            query_vector=query_vector,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            filters=filters,
            limit=limit,
        )

    def _dense_retrieve_python(
        self,
        *,
        query_vector: list[float],
        embedding_model: str,
        embedding_version: str,
        filters: PolicyRetrievalFilters,
        limit: int,
    ) -> list[RetrievedChunk]:
        statement = self._chunk_select_statement(filters, include_embedding=True).where(
            ChunkEmbedding.embedding_model == embedding_model,
            ChunkEmbedding.embedding_version == embedding_version,
        )
        rows = self.db.execute(statement).all()
        candidates: list[RetrievedChunk] = []
        for chunk, embedding, version, document in rows:
            vector = [float(value) for value in embedding.embedding]
            dense_score = cosine_similarity(query_vector, vector)
            candidates.append(
                row_to_retrieved_chunk(
                    chunk=chunk,
                    version=version,
                    document=document,
                    dense_score=dense_score,
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
        filters: PolicyRetrievalFilters,
        limit: int,
    ) -> list[RetrievedChunk]:
        where_sql, params, expanding = postgres_metadata_where(filters)
        statement = text(
            f"""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                c.version_id,
                c.chunk_text,
                c.heading_path,
                c.element_ids_json,
                c.order_index,
                d.title AS document_title,
                d.issuing_agency,
                d.document_no,
                d.source_url,
                d.publish_date,
                d.policy_level,
                d.validity_status,
                v.publish_status,
                1 - (e.embedding <=> CAST(:query_vector AS vector)) AS dense_score
            FROM chunk_embeddings e
            JOIN rag_chunks c ON c.id = e.chunk_id
            JOIN policy_document_versions v ON v.id = c.version_id
            JOIN policy_documents d ON d.id = c.document_id
            WHERE e.embedding_model = :embedding_model
              AND e.embedding_version = :embedding_version
              {where_sql}
            ORDER BY e.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        )
        for name in expanding:
            statement = statement.bindparams(bindparam(name, expanding=True))
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
        return [mapping_to_retrieved_chunk(row, dense_score=float(row["dense_score"] or 0.0)) for row in rows]

    def _keyword_retrieve(
        self,
        *,
        query: str,
        filters: PolicyRetrievalFilters,
        limit: int,
    ) -> list[RetrievedChunk]:
        terms = extract_query_terms(query)
        if not terms:
            return []
        rows = self.db.execute(
            apply_keyword_prefilter(
                self._chunk_select_statement(filters, include_embedding=False),
                terms=terms,
                query=query,
                result_limit=limit,
            )
        ).all()
        candidates: list[RetrievedChunk] = []
        for chunk, version, document in rows:
            keyword_score, exact_score = keyword_scores(
                query=query,
                terms=terms,
                text="\n".join([chunk.retrieval_text, document.title, document.document_no or ""]),
            )
            if keyword_score <= 0 and exact_score <= 0:
                continue
            candidates.append(
                row_to_retrieved_chunk(
                    chunk=chunk,
                    version=version,
                    document=document,
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
        filters: PolicyRetrievalFilters,
        limit: int,
    ) -> list[RetrievedChunk]:
        if self._dialect_name != "postgresql":
            return []
        where_sql, params, expanding = postgres_metadata_where(filters)
        statement = text(
            f"""
            SELECT
                c.id AS chunk_id,
                c.document_id,
                c.version_id,
                c.chunk_text,
                c.heading_path,
                c.element_ids_json,
                c.order_index,
                d.title AS document_title,
                d.issuing_agency,
                d.document_no,
                d.source_url,
                d.publish_date,
                d.policy_level,
                d.validity_status,
                v.publish_status,
                ts_rank(c.search_tsv, plainto_tsquery('simple', :query)) AS fulltext_score
            FROM rag_chunks c
            JOIN policy_document_versions v ON v.id = c.version_id
            JOIN policy_documents d ON d.id = c.document_id
            WHERE c.search_tsv @@ plainto_tsquery('simple', :query)
              {where_sql}
            ORDER BY fulltext_score DESC
            LIMIT :limit
            """
        )
        for name in expanding:
            statement = statement.bindparams(bindparam(name, expanding=True))
        rows = self.db.execute(
            statement,
            {**params, "query": query, "limit": limit},
        ).mappings()
        return [
            mapping_to_retrieved_chunk(row, fulltext_score=float(row["fulltext_score"] or 0.0))
            for row in rows
        ]

    def _chunk_select_statement(self, filters: PolicyRetrievalFilters, *, include_embedding: bool):
        columns = (
            (RagChunk, ChunkEmbedding, PolicyDocumentVersion, PolicyDocument)
            if include_embedding
            else (RagChunk, PolicyDocumentVersion, PolicyDocument)
        )
        statement = select(*columns).join(
            PolicyDocumentVersion,
            PolicyDocumentVersion.id == RagChunk.version_id,
        ).join(
            PolicyDocument,
            PolicyDocument.id == RagChunk.document_id,
        )
        if include_embedding:
            statement = statement.join(ChunkEmbedding, ChunkEmbedding.chunk_id == RagChunk.id)
        return apply_metadata_filters(statement, filters)

    @property
    def _dialect_name(self) -> str:
        if self.db.bind is None:
            return ""
        return self.db.bind.dialect.name


def apply_metadata_filters(statement, filters: PolicyRetrievalFilters):
    if filters.published_only:
        statement = statement.where(PolicyDocumentVersion.publish_status == "published")
    if filters.validity_statuses:
        statement = statement.where(PolicyDocument.validity_status.in_(filters.validity_statuses))
    if filters.policy_levels:
        statement = statement.where(PolicyDocument.policy_level.in_(filters.policy_levels))
    if filters.publish_date_from:
        statement = statement.where(PolicyDocument.publish_date >= filters.publish_date_from)
    if filters.publish_date_to:
        statement = statement.where(PolicyDocument.publish_date <= filters.publish_date_to)
    if filters.effective_date_from:
        statement = statement.where(PolicyDocument.effective_date >= filters.effective_date_from)
    if filters.effective_date_to:
        statement = statement.where(PolicyDocument.effective_date <= filters.effective_date_to)
    return statement


def apply_keyword_prefilter(statement, *, terms: list[str], query: str, result_limit: int):
    clauses = []
    rank_expressions = []
    for index, term in enumerate([query, *terms[:MAX_KEYWORD_PREFILTER_TERMS]]):
        like_pattern = f"%{escape_like(term)}%"
        chunk_match = RagChunk.search_text.ilike(like_pattern, escape="\\")
        title_match = PolicyDocument.title.ilike(like_pattern, escape="\\")
        document_no_match = PolicyDocument.document_no.ilike(like_pattern, escape="\\")
        clauses.extend([chunk_match, title_match, document_no_match])
        phrase_weight = 20 if index == 0 else 1
        rank_expressions.extend(
            [
                case((chunk_match, phrase_weight), else_=0),
                case((title_match, phrase_weight * 2), else_=0),
                case((document_no_match, phrase_weight * 3), else_=0),
            ]
        )
    candidate_limit = min(
        max(result_limit * KEYWORD_PREFILTER_MULTIPLIER, MIN_KEYWORD_PREFILTER_LIMIT),
        MAX_KEYWORD_PREFILTER_LIMIT,
    )
    rank_expression = sum(rank_expressions[1:], rank_expressions[0])
    return (
        statement.where(or_(*clauses))
        .order_by(rank_expression.desc(), RagChunk.order_index.asc())
        .limit(candidate_limit)
    )


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def postgres_metadata_where(filters: PolicyRetrievalFilters) -> tuple[str, dict[str, Any], list[str]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    expanding: list[str] = []
    if filters.published_only:
        clauses.append("AND v.publish_status = 'published'")
    if filters.validity_statuses:
        clauses.append("AND d.validity_status IN :validity_statuses")
        params["validity_statuses"] = list(filters.validity_statuses)
        expanding.append("validity_statuses")
    if filters.policy_levels:
        clauses.append("AND d.policy_level IN :policy_levels")
        params["policy_levels"] = list(filters.policy_levels)
        expanding.append("policy_levels")
    if filters.publish_date_from:
        clauses.append("AND d.publish_date >= :publish_date_from")
        params["publish_date_from"] = filters.publish_date_from
    if filters.publish_date_to:
        clauses.append("AND d.publish_date <= :publish_date_to")
        params["publish_date_to"] = filters.publish_date_to
    if filters.effective_date_from:
        clauses.append("AND d.effective_date >= :effective_date_from")
        params["effective_date_from"] = filters.effective_date_from
    if filters.effective_date_to:
        clauses.append("AND d.effective_date <= :effective_date_to")
        params["effective_date_to"] = filters.effective_date_to
    return "\n              ".join(clauses), params, expanding


def merge_candidate(
    candidates: dict[UUID, RetrievedChunk],
    candidate: RetrievedChunk,
    *,
    source: str,
) -> None:
    existing = candidates.get(candidate.chunk_id)
    if existing is None:
        candidate.match_sources = [source]
        candidates[candidate.chunk_id] = candidate
        return

    existing.dense_score = max(existing.dense_score, candidate.dense_score)
    existing.keyword_score = max(existing.keyword_score, candidate.keyword_score)
    existing.fulltext_score = max(existing.fulltext_score, candidate.fulltext_score)
    existing.exact_score = max(existing.exact_score, candidate.exact_score)
    if source not in existing.match_sources:
        existing.match_sources.append(source)


def rerank_candidates(
    *,
    candidates: list[RetrievedChunk],
    query: str,
    filters: PolicyRetrievalFilters,
) -> list[RetrievedChunk]:
    query_level = infer_policy_level_from_query(query)
    for candidate in candidates:
        candidate.metadata_score = metadata_score(candidate, filters=filters, query_level=query_level)
        candidate.final_score = (
            candidate.dense_score * 0.62
            + candidate.keyword_score * 0.22
            + candidate.fulltext_score * 0.08
            + candidate.exact_score * 0.25
            + candidate.metadata_score
        )
    return sorted(candidates, key=lambda candidate: candidate.final_score, reverse=True)


def limit_chunks_per_document(
    candidates: list[RetrievedChunk],
    *,
    top_k: int,
    max_per_document: int = MAX_CHUNKS_PER_DOCUMENT,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    document_counts: dict[UUID, int] = {}
    for candidate in candidates:
        count = document_counts.get(candidate.document_id, 0)
        if count >= max_per_document:
            continue
        selected.append(candidate)
        document_counts[candidate.document_id] = count + 1
        if len(selected) >= top_k:
            break
    return selected


def metadata_score(
    candidate: RetrievedChunk,
    *,
    filters: PolicyRetrievalFilters,
    query_level: str | None,
) -> float:
    score = 0.0
    if candidate.validity_status == "active":
        score += 0.08
    elif candidate.validity_status == "unknown":
        score += 0.03
    if filters.policy_levels and candidate.policy_level in filters.policy_levels:
        score += 0.05
    if query_level and candidate.policy_level == query_level:
        score += 0.06
    if candidate.publish_status == "published":
        score += 0.04
    return score


def row_to_retrieved_chunk(
    *,
    chunk: RagChunk,
    version: PolicyDocumentVersion,
    document: PolicyDocument,
    dense_score: float = 0.0,
    keyword_score: float = 0.0,
    fulltext_score: float = 0.0,
    exact_score: float = 0.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        version_id=chunk.version_id,
        chunk_text=chunk.chunk_text,
        heading_path=chunk.heading_path,
        element_ids=list(chunk.element_ids_json or []),
        order_index=chunk.order_index,
        document_title=document.title,
        issuing_agency=document.issuing_agency,
        document_no=document.document_no,
        source_url=document.source_url,
        publish_date=document.publish_date,
        policy_level=document.policy_level,
        validity_status=document.validity_status,
        publish_status=version.publish_status,
        dense_score=dense_score,
        keyword_score=keyword_score,
        fulltext_score=fulltext_score,
        exact_score=exact_score,
    )


def mapping_to_retrieved_chunk(
    row: Any,
    *,
    dense_score: float = 0.0,
    fulltext_score: float = 0.0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        version_id=row["version_id"],
        chunk_text=row["chunk_text"],
        heading_path=row["heading_path"],
        element_ids=list(row["element_ids_json"] or []),
        order_index=int(row["order_index"]),
        document_title=row["document_title"],
        issuing_agency=row["issuing_agency"],
        document_no=row["document_no"],
        source_url=row["source_url"],
        publish_date=row["publish_date"],
        policy_level=row["policy_level"],
        validity_status=row["validity_status"],
        publish_status=row["publish_status"],
        dense_score=dense_score,
        fulltext_score=fulltext_score,
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(left * right for left, right in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def keyword_scores(*, query: str, terms: list[str], text: str) -> tuple[float, float]:
    normalized_text = normalize_query(text)
    exact_score = 1.0 if query in normalized_text else 0.0
    hit_count = sum(1 for term in terms if term in normalized_text)
    keyword_score = hit_count / max(len(terms), 1)
    return keyword_score, exact_score


def extract_query_terms(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", normalize_query(query))
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        for term in token_to_query_terms(token):
            if term not in seen:
                seen.add(term)
                result.append(term)
            if len(result) >= MAX_QUERY_TERMS:
                return result
    return result


def token_to_query_terms(token: str) -> list[str]:
    if not re.fullmatch(r"[\u4e00-\u9fff]+", token):
        return [token]
    if token in CHINESE_STOP_TERMS:
        return []
    if len(token) <= 4:
        return [token]
    return [
        token[index : index + 2]
        for index in range(len(token) - 1)
        if token[index : index + 2] not in CHINESE_STOP_TERMS
    ]


def infer_policy_level_from_query(query: str) -> str | None:
    if any(keyword in query for keyword in ("国家", "全国", "国家级")):
        return "national"
    if any(keyword in query for keyword in ("省", "自治区")):
        return "province"
    if any(keyword in query for keyword in ("市", "北京", "上海", "广州", "深圳")):
        return "city"
    if any(keyword in query for keyword in ("区", "县")):
        return "district"
    return None


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())
