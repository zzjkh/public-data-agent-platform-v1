from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.db.models.document import PolicyDocument, PolicyDocumentVersion, SourceFile
from app.db.models.ingestion_job import IngestionJob
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


def test_parse_policy_document_job_creates_version_and_elements(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    html = """
    <html>
      <body>
        <h1>公共数据开放管理办法</h1>
        <p>第一条 为规范公共数据开放，制定本办法。</p>
        <h2>第一章 开放范围</h2>
        <p>第二条 公共数据应当依法有序开放。</p>
      </body>
    </html>
    """.encode()

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy.html", html, "text/html")},
            data={"source_url": "https://example.com/policy.html"},
        )
        source_file_id = upload_response.json()["file_id"]
        job_response = client.post(
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
        job_id = UUID(job_response.json()["job_id"])

        with SessionLocal() as db:
            processed = run_worker_once(
                db=db,
                settings=settings,
                handlers=get_default_job_handlers(settings),
            )
            assert processed is not None

        detail_response = client.get(f"/api/jobs/{job_id}", headers=headers)
        version_id = detail_response.json()["result_json"]["version_id"]
        elements_response = client.get(
            f"/api/document-versions/{version_id}/elements",
            headers=headers,
        )

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "success"
    assert detail_response.json()["result_json"]["element_count"] == 4
    assert elements_response.status_code == 200
    elements = elements_response.json()["items"]
    assert elements[0]["content"] == "公共数据开放管理办法"
    assert elements[2]["heading_level"] == 2
    assert elements[2]["parent_id"] == elements[0]["id"]

    with SessionLocal() as db:
        source_file = db.get(SourceFile, UUID(source_file_id))
        version = db.get(PolicyDocumentVersion, UUID(version_id))
        job = db.get(IngestionJob, job_id)

    assert source_file is not None
    assert source_file.parse_status == "parsed"
    assert version is not None
    assert version.parser_type == "html"
    assert job is not None
    assert job.progress_percent == 100


def test_parse_policy_document_reuses_same_content_hash(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    html = "<html><body><h1>重复政策</h1><p>同一份正文。</p></body></html>".encode()

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("same.html", html, "text/html")},
        )
        source_file_id = upload_response.json()["file_id"]
        first_job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "parse_policy_document",
                "target_type": "source_file",
                "target_id": source_file_id,
                "max_retries": 0,
            },
        )
        first_job_id = UUID(first_job_response.json()["job_id"])
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            first_result = db.get(IngestionJob, first_job_id).result_json

        second_job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "parse_policy_document",
                "target_type": "source_file",
                "target_id": source_file_id,
                "max_retries": 0,
            },
        )
        second_job_id = UUID(second_job_response.json()["job_id"])
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            second_result = db.get(IngestionJob, second_job_id).result_json

    assert second_result["version_id"] == first_result["version_id"]
    assert second_result["reused_existing_version"]
    with SessionLocal() as db:
        assert db.query(PolicyDocument).count() == 1


def test_document_elements_endpoint_requires_existing_version(tmp_path: Path) -> None:
    client, _ = make_test_client(tmp_path)

    with client:
        headers = auth_headers(client)
        response = client.get(
            "/api/document-versions/00000000-0000-0000-0000-000000000001/elements",
            headers=headers,
        )

    assert response.status_code == 404
