from __future__ import annotations

import hashlib
from pathlib import Path

from tests.helpers import auth_headers, make_test_client


def test_admin_can_upload_and_list_source_files(tmp_path: Path) -> None:
    client, _ = make_test_client(tmp_path)
    content = b"<html><body>policy</body></html>"

    with client:
        headers = auth_headers(client)
        response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy.html", content, "text/html")},
            data={"source_url": "https://example.com/policy", "file_version": "v1"},
        )
        duplicate_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy-copy.html", content, "text/html")},
            data={"source_url": "https://example.com/policy-copy", "file_version": "v2"},
        )
        list_response = client.get("/api/files", headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["file_hash"] == hashlib.sha256(content).hexdigest()
    assert body["parse_status"] == "pending"
    assert body["request_id"]
    assert (tmp_path / body["storage_uri"].removeprefix("local://")).exists()

    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["file_id"] == body["file_id"]

    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["total"] == 1
    assert list_body["items"][0]["file_name"] == "policy.html"


def test_upload_requires_admin_role(tmp_path: Path) -> None:
    client, _ = make_test_client(tmp_path)

    with client:
        headers = auth_headers(client, username="demo", password="demo123")
        response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy.html", b"<html></html>", "text/html")},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "HTTP_403"


def test_upload_rejects_unsupported_file_type(tmp_path: Path) -> None:
    client, _ = make_test_client(tmp_path)

    with client:
        headers = auth_headers(client)
        response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy.txt", b"text", "text/plain")},
        )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["error"]["message"]
