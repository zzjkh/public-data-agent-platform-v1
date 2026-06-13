from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from app.db.models.document import DocumentElement
from app.db.models.ingestion_job import IngestionJob
from app.db.models.rag_chunk import RagChunk
from app.ingestion.chunking import build_chunk_specs
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


def make_element(
    *,
    document_id: UUID,
    version_id: UUID,
    order_index: int,
    element_type: str,
    content: str,
    heading_level: int | None = None,
) -> DocumentElement:
    return DocumentElement(
        id=uuid4(),
        document_id=document_id,
        version_id=version_id,
        element_type=element_type,
        content=content,
        order_index=order_index,
        heading_level=heading_level,
        metadata_json={},
    )


def test_chunking_keeps_heading_path_and_uses_sliding_window_for_long_text() -> None:
    document_id = uuid4()
    version_id = uuid4()
    long_text = "公共数据应当依法有序开放，保护个人信息和商业秘密。" * 8
    elements = [
        make_element(
            document_id=document_id,
            version_id=version_id,
            order_index=0,
            element_type="title",
            content="公共数据开放管理办法",
            heading_level=1,
        ),
        make_element(
            document_id=document_id,
            version_id=version_id,
            order_index=1,
            element_type="paragraph",
            content="第一条 为规范公共数据开放，制定本办法。",
        ),
        make_element(
            document_id=document_id,
            version_id=version_id,
            order_index=2,
            element_type="title",
            content="第一章 开放范围",
            heading_level=2,
        ),
        make_element(
            document_id=document_id,
            version_id=version_id,
            order_index=3,
            element_type="paragraph",
            content=long_text,
        ),
    ]

    specs = build_chunk_specs(
        elements,
        document_title="公共数据开放管理办法",
        issuing_agency="测试部门",
        min_chars=40,
        max_chars=90,
        overlap_ratio=0.12,
    )

    assert specs[0].chunk_strategy == "section"
    assert specs[0].heading_path == "公共数据开放管理办法"
    assert any(spec.chunk_strategy == "sliding_window" for spec in specs)
    assert any(spec.heading_path == "公共数据开放管理办法 / 第一章 开放范围" for spec in specs)
    assert all(spec.element_ids for spec in specs)
    assert all("文件标题：公共数据开放管理办法" in spec.embedding_text for spec in specs)


def test_sliding_window_overlap_is_stable() -> None:
    document_id = uuid4()
    version_id = uuid4()
    text = "".join(f"{index:03d}" for index in range(60))
    elements = [
        make_element(
            document_id=document_id,
            version_id=version_id,
            order_index=0,
            element_type="paragraph",
            content=text,
        )
    ]

    specs = build_chunk_specs(
        elements,
        document_title="窗口测试",
        issuing_agency=None,
        chunk_strategy="sliding_window",
        min_chars=10,
        max_chars=50,
        overlap_ratio=0.12,
    )

    assert len(specs) > 1
    assert specs[0].chunk_text[-6:] == specs[1].chunk_text[:6]


def test_build_rag_chunks_job_creates_chunks_and_reuses_hashes(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
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

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy.html", html, "text/html")},
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
            parse_result = db.get(IngestionJob, parse_job_id).result_json

        version_id = parse_result["version_id"]
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

        detail_response = client.get(f"/api/jobs/{chunk_job_id}", headers=headers)
        chunks_response = client.get(f"/api/document-versions/{version_id}/chunks", headers=headers)

        second_chunk_job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "build_rag_chunks",
                "target_type": "document_version",
                "target_id": version_id,
                "max_retries": 0,
            },
        )
        second_chunk_job_id = UUID(second_chunk_job_response.json()["job_id"])
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            second_result = db.get(IngestionJob, second_chunk_job_id).result_json

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "success"
    assert detail_response.json()["result_json"]["chunk_strategy"] == "section"
    assert detail_response.json()["result_json"]["chunk_count"] >= 1

    assert chunks_response.status_code == 200
    chunks = chunks_response.json()["items"]
    assert chunks_response.json()["total"] == detail_response.json()["result_json"]["chunk_count"]
    assert chunks[0]["order_index"] == 0
    assert chunks[0]["prev_chunk_id"] is None
    assert chunks[-1]["next_chunk_id"] is None
    assert chunks[0]["embedding_text"].startswith("文件标题：公共数据开放管理办法")
    assert chunks[0]["element_ids_json"]

    assert second_result["chunk_count"] == len(chunks)
    assert second_result["reused_existing_chunks"] == len(chunks)

    with SessionLocal() as db:
        persisted_chunks = db.query(RagChunk).filter(RagChunk.version_id == UUID(version_id)).all()

    assert len(persisted_chunks) == len(chunks)
