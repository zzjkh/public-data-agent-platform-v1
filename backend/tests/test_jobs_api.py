from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.db.models.ingestion_job import IngestionJob
from tests.helpers import auth_headers, make_test_client


def test_admin_can_create_list_get_and_cancel_job(tmp_path: Path) -> None:
    client, _ = make_test_client(tmp_path)

    with client:
        headers = auth_headers(client)
        create_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "build_chunk_embeddings",
                "target_type": "document_version",
                "payload": {"embedding_model": "BAAI/bge-small-zh-v1.5"},
            },
        )
        job_id = create_response.json()["job_id"]
        detail_response = client.get(f"/api/jobs/{job_id}", headers=headers)
        list_response = client.get("/api/jobs?status=pending", headers=headers)
        cancel_response = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "pending"
    assert create_response.json()["request_id"]

    assert detail_response.status_code == 200
    assert detail_response.json()["job_type"] == "build_chunk_embeddings"
    assert detail_response.json()["request_id"]

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"


def test_retry_failed_job_resets_state(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)

    with client:
        headers = auth_headers(client)
        create_response = client.post(
            "/api/jobs",
            headers=headers,
            json={"job_type": "parse_policy_document", "target_type": "source_file"},
        )
        job_id = UUID(create_response.json()["job_id"])

        with SessionLocal() as db:
            job = db.get(IngestionJob, job_id)
            assert job is not None
            job.status = "failed"
            job.error_message = "parser failed"
            job.retry_count = 2
            db.commit()

        retry_response = client.post(f"/api/jobs/{job_id}/retry", headers=headers)

    assert retry_response.status_code == 200
    body = retry_response.json()
    assert body["status"] == "pending"
    assert body["retry_count"] == 0
    assert body["error_message"] is None


def test_retry_rejects_non_failed_job(tmp_path: Path) -> None:
    client, _ = make_test_client(tmp_path)

    with client:
        headers = auth_headers(client)
        create_response = client.post(
            "/api/jobs",
            headers=headers,
            json={"job_type": "parse_policy_document", "target_type": "source_file"},
        )
        job_id = create_response.json()["job_id"]
        retry_response = client.post(f"/api/jobs/{job_id}/retry", headers=headers)

    assert retry_response.status_code == 409
    assert "Only failed jobs" in retry_response.json()["error"]["message"]
