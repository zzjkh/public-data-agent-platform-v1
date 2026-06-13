from __future__ import annotations

from pathlib import Path
from uuid import UUID

import fitz

from app.db.models.document import PolicyDocumentVersion, SourceFile
from app.db.models.ingestion_job import IngestionJob
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.parsers.ocr_engine import OcrTextBlock
from app.ingestion.parsers.pdf_ocr_parser import parse_pdf_ocr_document
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


class FakeOcrEngine:
    name = "fake-ocr"

    def recognize(self, image_path: str | Path, *, lang: str) -> list[OcrTextBlock]:
        return [
            OcrTextBlock("扫描政策标题", (20, 20, 260, 60), 96.5),
            OcrTextBlock("第一章 总则", (20, 110, 220, 145), 94.0),
            OcrTextBlock("第一条 为规范公共数据开放，", (20, 170, 420, 200), 91.0),
            OcrTextBlock("制定本办法。", (20, 205, 220, 235), 90.0),
        ]


class EmptyOcrEngine:
    name = "empty-ocr"

    def recognize(self, image_path: str | Path, *, lang: str) -> list[OcrTextBlock]:
        return []


def create_blank_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page(width=595, height=842)
    document.save(path)
    document.close()


def test_pdf_ocr_parser_extracts_elements_with_mock_engine(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned-policy.pdf"
    create_blank_pdf(pdf_path)

    parsed = parse_pdf_ocr_document(
        pdf_path,
        fallback_title="scanned-policy.pdf",
        ocr_engine=FakeOcrEngine(),
        render_dpi=144,
    )

    assert parsed.title == "扫描政策标题"
    assert parsed.page_count == 1
    assert parsed.ocr_engine == "fake-ocr"
    assert parsed.elements[0].element_type == "title"
    assert parsed.elements[0].heading_level == 1
    assert parsed.elements[0].bbox == {"x0": 10.0, "y0": 10.0, "x1": 130.0, "y1": 30.0}
    assert parsed.elements[0].metadata["confidence"] == 96.5
    assert any(element.heading_level == 2 for element in parsed.elements)
    assert "第一条 为规范公共数据开放，制定本办法。" in parsed.clean_text
    assert "# 扫描政策标题" in parsed.markdown_text


def test_pdf_ocr_parse_policy_document_job_with_mock_engine(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "scanned-policy.pdf"
    create_blank_pdf(pdf_path)
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    monkeypatch.setattr("app.ingestion.handlers.build_ocr_engine", lambda _: FakeOcrEngine())

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("scanned-policy.pdf", pdf_path.read_bytes(), "application/pdf")},
            data={"source_url": "https://example.com/scanned-policy.pdf"},
        )
        source_file_id = upload_response.json()["file_id"]
        job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "parse_policy_document",
                "target_type": "source_file",
                "target_id": source_file_id,
                "payload": {"parser_type": "pdf_ocr"},
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
    assert detail_response.json()["result_json"]["parser_type"] == "pdf_ocr"
    assert elements_response.status_code == 200
    elements = elements_response.json()["items"]
    assert elements[0]["content"] == "扫描政策标题"
    assert elements[0]["metadata_json"]["ocr_engine"] == "fake-ocr"

    with SessionLocal() as db:
        source_file = db.get(SourceFile, UUID(source_file_id))
        version = db.get(PolicyDocumentVersion, UUID(version_id))
        job = db.get(IngestionJob, job_id)

    assert source_file is not None
    assert source_file.parse_status == "parsed"
    assert version is not None
    assert version.parser_type == "pdf_ocr"
    assert version.parse_json["ocr_engine"] == "fake-ocr"
    assert version.parse_json["render_dpi"] == settings.ocr_render_dpi
    assert job is not None
    assert job.progress_percent == 100


def test_pdf_ocr_job_fails_cleanly_when_ocr_returns_no_text(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "empty-scan.pdf"
    create_blank_pdf(pdf_path)
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    monkeypatch.setattr("app.ingestion.handlers.build_ocr_engine", lambda _: EmptyOcrEngine())

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("empty-scan.pdf", pdf_path.read_bytes(), "application/pdf")},
        )
        source_file_id = upload_response.json()["file_id"]
        job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "parse_policy_document",
                "target_type": "source_file",
                "target_id": source_file_id,
                "payload": {"parser_type": "pdf_ocr"},
                "max_retries": 0,
            },
        )
        job_id = UUID(job_response.json()["job_id"])

        with SessionLocal() as db:
            run_worker_once(
                db=db,
                settings=settings,
                handlers=get_default_job_handlers(settings),
            )

        detail_response = client.get(f"/api/jobs/{job_id}", headers=headers)

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "failed"
    assert "too little text" in detail_response.json()["error_message"]

    with SessionLocal() as db:
        source_file = db.get(SourceFile, UUID(source_file_id))

    assert source_file is not None
    assert source_file.parse_status == "failed"


def test_pdf_ocr_job_respects_ocr_enabled_flag(tmp_path: Path) -> None:
    pdf_path = tmp_path / "disabled-ocr.pdf"
    create_blank_pdf(pdf_path)
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    settings.ocr_enabled = False

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("disabled-ocr.pdf", pdf_path.read_bytes(), "application/pdf")},
        )
        source_file_id = upload_response.json()["file_id"]
        job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "parse_policy_document",
                "target_type": "source_file",
                "target_id": source_file_id,
                "payload": {"parser_type": "pdf_ocr"},
                "max_retries": 0,
            },
        )
        job_id = UUID(job_response.json()["job_id"])

        with SessionLocal() as db:
            run_worker_once(
                db=db,
                settings=settings,
                handlers=get_default_job_handlers(settings),
            )

        detail_response = client.get(f"/api/jobs/{job_id}", headers=headers)

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "failed"
    assert "OCR is disabled" in detail_response.json()["error_message"]

    with SessionLocal() as db:
        source_file = db.get(SourceFile, UUID(source_file_id))

    assert source_file is not None
    assert source_file.parse_status == "failed"
