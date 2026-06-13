from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.db.models.document import PolicyDocument, PolicyDocumentVersion
from app.db.models.rag_chunk import ChunkEmbedding, RagChunk
from app.rag.context_builder import ContextBuilder
from app.rag.retriever import (
    MIN_KEYWORD_PREFILTER_LIMIT,
    PolicyRetrievalFilters,
    PolicyRetriever,
    apply_keyword_prefilter,
    limit_chunks_per_document,
)
from tests.helpers import make_test_client


class FakeQueryEmbeddingProvider:
    model_name = "fake-bge"
    embedding_dim = 3

    def __init__(self, query_vector: list[float]) -> None:
        self.query_vector = query_vector

    def embed_query(self, text: str) -> list[float]:
        return self.query_vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.query_vector for _ in texts]


def seed_policy_chunk(
    db,
    *,
    title: str,
    chunk_text: str,
    vector: list[float],
    policy_level: str = "city",
    validity_status: str = "active",
    publish_date: date | None = date(2026, 1, 1),
) -> RagChunk:
    document = PolicyDocument(
        title=title,
        issuing_agency="测试部门",
        document_no=f"TEST-{uuid4().hex[:6]}",
        source_url=f"https://example.com/{uuid4().hex}",
        publish_date=publish_date,
        policy_level=policy_level,
        validity_status=validity_status,
        keywords_json={},
    )
    db.add(document)
    db.flush()

    version = PolicyDocumentVersion(
        document_id=document.id,
        version_no="v1",
        raw_text=chunk_text,
        clean_text=chunk_text,
        markdown_text=chunk_text,
        parse_json={},
        content_hash=uuid4().hex,
        publish_status="published",
        parser_type="html",
    )
    db.add(version)
    db.flush()

    chunk = RagChunk(
        document_id=document.id,
        version_id=version.id,
        chunk_text=chunk_text,
        embedding_text=f"文件标题：{title}\n正文：{chunk_text}",
        retrieval_text=f"{title}\n{chunk_text}",
        heading_path=f"{title} / 第一章",
        element_ids_json=[str(uuid4())],
        order_index=0,
        chunk_strategy="section",
        char_count=len(chunk_text),
        token_count=len(chunk_text),
        content_hash=uuid4().hex,
        search_text=f"{title}\n{chunk_text}",
    )
    db.add(chunk)
    db.flush()

    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            embedding_model="fake-bge",
            embedding_dim=3,
            embedding_version="v1",
            embedding=vector,
        )
    )
    db.flush()
    return chunk


def test_policy_retriever_merges_dense_and_keyword_hits(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)

    with SessionLocal() as db:
        target_chunk = seed_policy_chunk(
            db,
            title="公共数据开放管理办法",
            chunk_text="公共数据开放应当保护个人信息和商业秘密。",
            vector=[1.0, 0.0, 0.0],
        )
        seed_policy_chunk(
            db,
            title="财政预算管理办法",
            chunk_text="财政预算应当依法公开。",
            vector=[0.0, 1.0, 0.0],
        )
        db.commit()

        result = PolicyRetriever(db).retrieve(
            query="公共数据开放如何保护个人信息",
            embedding_provider=FakeQueryEmbeddingProvider([1.0, 0.0, 0.0]),
            embedding_model="fake-bge",
            embedding_version="v1",
            top_k=3,
        )

    assert result.chunks
    assert result.chunks[0].chunk_id == target_chunk.id
    assert "dense" in result.chunks[0].match_sources
    assert "keyword" in result.chunks[0].match_sources
    assert result.chunks[0].keyword_score > 0
    assert result.chunks[0].final_score > 0


def test_policy_retriever_applies_metadata_filters(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)

    with SessionLocal() as db:
        seed_policy_chunk(
            db,
            title="已废止公共数据政策",
            chunk_text="公共数据开放。",
            vector=[1.0, 0.0, 0.0],
            validity_status="abolished",
        )
        national_chunk = seed_policy_chunk(
            db,
            title="国家公共数据政策",
            chunk_text="国家层面推进公共数据资源开发利用。",
            vector=[0.9, 0.1, 0.0],
            policy_level="national",
        )
        seed_policy_chunk(
            db,
            title="市级公共数据政策",
            chunk_text="市级公共数据开放管理。",
            vector=[0.8, 0.2, 0.0],
            policy_level="city",
        )
        db.commit()

        result = PolicyRetriever(db).retrieve(
            query="国家公共数据政策",
            embedding_provider=FakeQueryEmbeddingProvider([1.0, 0.0, 0.0]),
            embedding_model="fake-bge",
            embedding_version="v1",
            filters=PolicyRetrievalFilters(policy_levels=("national",)),
            top_k=5,
        )

    assert [chunk.chunk_id for chunk in result.chunks] == [national_chunk.id]
    assert result.chunks[0].policy_level == "national"
    assert result.chunks[0].validity_status != "abolished"


def test_keyword_prefilter_limits_database_candidate_pool(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)

    with SessionLocal() as db:
        statement = apply_keyword_prefilter(
            PolicyRetriever(db)._chunk_select_statement(
                PolicyRetrievalFilters(),
                include_embedding=False,
            ),
            terms=["公共", "数据"],
            query="公共数据",
            result_limit=5,
        )
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True})).upper()

    assert "ORDER BY" in compiled
    assert f"LIMIT {MIN_KEYWORD_PREFILTER_LIMIT}" in compiled


def test_retrieval_limits_chunks_from_the_same_document(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)

    with SessionLocal() as db:
        seed_policy_chunk(
            db,
            title="公共数据开放管理办法",
            chunk_text="公共数据开放应当依法有序推进。",
            vector=[1.0, 0.0, 0.0],
        )
        db.commit()
        base = PolicyRetriever(db).retrieve(
            query="公共数据开放",
            embedding_provider=FakeQueryEmbeddingProvider([1.0, 0.0, 0.0]),
            embedding_model="fake-bge",
            embedding_version="v1",
            top_k=1,
        ).chunks[0]

    other_document_id = uuid4()
    candidates = [
        replace(base, chunk_id=uuid4(), final_score=1.0),
        replace(base, chunk_id=uuid4(), final_score=0.9),
        replace(base, chunk_id=uuid4(), final_score=0.8),
        replace(
            base,
            chunk_id=uuid4(),
            document_id=other_document_id,
            final_score=0.7,
        ),
    ]

    selected = limit_chunks_per_document(candidates, top_k=3)

    assert len(selected) == 3
    assert sum(chunk.document_id == base.document_id for chunk in selected) == 2
    assert selected[-1].document_id == other_document_id


def test_context_builder_returns_numbered_evidence_blocks(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)

    with SessionLocal() as db:
        seed_policy_chunk(
            db,
            title="公共数据开放管理办法",
            chunk_text="公共数据开放应当依法有序推进。",
            vector=[1.0, 0.0, 0.0],
        )
        db.commit()

        result = PolicyRetriever(db).retrieve(
            query="公共数据开放",
            embedding_provider=FakeQueryEmbeddingProvider([1.0, 0.0, 0.0]),
            embedding_model="fake-bge",
            embedding_version="v1",
            top_k=1,
        )
        context = ContextBuilder().build(result.chunks)

    assert len(context.evidence_blocks) == 1
    assert context.evidence_blocks[0].source_id == "资料1"
    assert "标题：公共数据开放管理办法" in context.context_text
    assert "正文：公共数据开放应当依法有序推进。" in context.context_text
