from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.db.models.ingestion_job import IngestionJob
from app.db.models.rag_chunk import ChunkEmbedding, RagChunk
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


class FakeEmbeddingProvider:
    def __init__(self, *, model_name: str = "fake-bge", embedding_dim: int = 512) -> None:
        self.model_name = model_name
        self.embedding_dim = embedding_dim
        self.calls: list[list[str]] = []

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [fake_vector(text, self.embedding_dim) for text in texts]


def fake_vector(text: str, dim: int) -> list[float]:
    seed = sum(ord(char) for char in text) % 97
    return [float((seed + index) % 17) / 17.0 for index in range(dim)]


def create_parsed_chunks(client, SessionLocal, settings, headers: dict[str, str]) -> str:
    html = """
    <html>
      <body>
        <h1>公共数据开放管理办法</h1>
        <p>第一条 为规范公共数据开放，制定本办法。</p>
        <h2>第一章 开放范围</h2>
        <p>第二条 公共数据应当依法有序开放。</p>
        <p>第三条 开放过程应当保护个人信息、商业秘密和公共安全。</p>
      </body>
    </html>
    """.encode()
    upload_response = client.post(
        "/api/files/upload",
        headers=headers,
        files={"file": ("embedding-policy.html", html, "text/html")},
    )
    source_file_id = upload_response.json()["file_id"]
    parse_job_response = client.post(
        "/api/jobs",
        headers=headers,
        json={
            "job_type": "parse_policy_document",
            "target_type": "source_file",
            "target_id": source_file_id,
            "payload": {"parser_type": "html"},
            "max_retries": 0,
        },
    )
    parse_job_id = UUID(parse_job_response.json()["job_id"])
    with SessionLocal() as db:
        run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
        version_id = db.get(IngestionJob, parse_job_id).result_json["version_id"]

    chunk_job_response = client.post(
        "/api/jobs",
        headers=headers,
        json={
            "job_type": "build_rag_chunks",
            "target_type": "document_version",
            "target_id": version_id,
            "max_retries": 0,
        },
    )
    chunk_job_id = UUID(chunk_job_response.json()["job_id"])
    with SessionLocal() as db:
        run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
        chunk_job = db.get(IngestionJob, chunk_job_id)
        assert chunk_job.status == "success"

    return version_id


def test_build_chunk_embeddings_job_writes_and_reuses_embeddings(tmp_path: Path, monkeypatch) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    provider = FakeEmbeddingProvider(model_name=settings.embedding_model, embedding_dim=settings.embedding_dim)
    monkeypatch.setattr("app.ingestion.handlers.build_embedding_provider", lambda *_args, **_kwargs: provider)

    with client:
        headers = auth_headers(client)
        version_id = create_parsed_chunks(client, SessionLocal, settings, headers)
        embedding_job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "build_chunk_embeddings",
                "target_type": "document_version",
                "target_id": version_id,
                "payload": {"batch_size": 1},
                "max_retries": 0,
            },
        )
        embedding_job_id = UUID(embedding_job_response.json()["job_id"])

        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            embedding_job = db.get(IngestionJob, embedding_job_id)
            first_result = embedding_job.result_json

        second_job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "build_chunk_embeddings",
                "target_type": "document_version",
                "target_id": version_id,
                "max_retries": 0,
            },
        )
        second_job_id = UUID(second_job_response.json()["job_id"])
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            second_result = db.get(IngestionJob, second_job_id).result_json

    assert first_result["embedding_model"] == settings.embedding_model
    assert first_result["embedding_dim"] == settings.embedding_dim
    assert first_result["embedding_version"] == settings.embedding_version
    assert first_result["chunk_count"] >= 1
    assert first_result["created_embeddings"] == first_result["chunk_count"]
    assert first_result["reused_existing_embeddings"] == 0
    assert len(provider.calls) == first_result["chunk_count"]

    assert second_result["created_embeddings"] == 0
    assert second_result["reused_existing_embeddings"] == first_result["chunk_count"]

    with SessionLocal() as db:
        chunks = db.query(RagChunk).filter(RagChunk.version_id == UUID(version_id)).all()
        embeddings = db.query(ChunkEmbedding).all()

    assert len(embeddings) == len(chunks)
    assert len(embeddings[0].embedding) == settings.embedding_dim


def test_build_chunk_embeddings_job_fails_on_provider_dim_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    monkeypatch.setattr(
        "app.ingestion.handlers.build_embedding_provider",
        lambda *_args, **_kwargs: FakeEmbeddingProvider(embedding_dim=3),
    )

    with client:
        headers = auth_headers(client)
        version_id = create_parsed_chunks(client, SessionLocal, settings, headers)
        embedding_job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "build_chunk_embeddings",
                "target_type": "document_version",
                "target_id": version_id,
                "max_retries": 0,
            },
        )
        embedding_job_id = UUID(embedding_job_response.json()["job_id"])

        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))

        detail_response = client.get(f"/api/jobs/{embedding_job_id}", headers=headers)

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "failed"
    assert "Provider dim mismatch" in detail_response.json()["error_message"]
