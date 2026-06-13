from __future__ import annotations

from pathlib import Path
from uuid import UUID

import fitz

from app.db.models.document import PolicyDocumentVersion, SourceFile
from app.db.models.ingestion_job import IngestionJob
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.parsers.pdf_text_parser import parse_pdf_text_document
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


def create_sample_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "Public Data Policy", fontsize=20)
    page.insert_text((72, 120), "Article 1 This policy validates PDF parsing.", fontsize=12)
    page.insert_text((72, 160), "Chapter 1 Scope", fontsize=16)
    page.insert_text((72, 190), "Article 2 Public data should be opened safely.", fontsize=12)

    x0, y0 = 72, 240
    cell_width, cell_height = 120, 28
    rows, columns = 3, 2
    for row in range(rows + 1):
        y = y0 + row * cell_height
        page.draw_line((x0, y), (x0 + columns * cell_width, y), color=(0, 0, 0), width=0.8)
    for column in range(columns + 1):
        x = x0 + column * cell_width
        page.draw_line((x, y0), (x, y0 + rows * cell_height), color=(0, 0, 0), width=0.8)

    table_text = [
        ["Metric", "Value"],
        ["Datasets", "1200"],
        ["APIs", "88"],
    ]
    for row_index, row in enumerate(table_text):
        for column_index, cell in enumerate(row):
            page.insert_text(
                (x0 + column_index * cell_width + 8, y0 + row_index * cell_height + 18),
                cell,
                fontsize=10,
            )

    document.save(path)
    document.close()


def test_pdf_text_parser_extracts_layout_elements_and_table(tmp_path: Path) -> None:
    pdf_path = tmp_path / "policy.pdf"
    create_sample_pdf(pdf_path)

    parsed = parse_pdf_text_document(pdf_path, fallback_title="policy.pdf")

    assert parsed.title == "Public Data Policy"
    assert parsed.page_count == 1
    assert parsed.elements[0].element_type == "title"
    assert parsed.elements[0].heading_level == 1
    assert parsed.elements[0].page_no == 1
    assert parsed.elements[0].bbox
    assert "Article 1" in parsed.clean_text
    assert any(element.element_type == "table" for element in parsed.elements)
    table = next(element for element in parsed.elements if element.element_type == "table")
    assert "Metric | Value" in table.content
    assert table.bbox is not None
    assert "# Public Data Policy" in parsed.markdown_text
    assert parsed.table_extraction_errors == []


def test_pdf_text_parser_keeps_text_when_table_extraction_fails(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "policy.pdf"
    create_sample_pdf(pdf_path)

    class BrokenPage:
        def find_tables(self):
            raise KeyError("N")

    class BrokenDocument:
        pages = [BrokenPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.ingestion.parsers.pdf_text_parser.pdfplumber.open",
        lambda _path: BrokenDocument(),
    )

    parsed = parse_pdf_text_document(pdf_path, fallback_title="policy.pdf")

    assert "Article 1" in parsed.clean_text
    assert not any(element.element_type == "table" for element in parsed.elements)
    assert parsed.table_extraction_errors == ["page 1: KeyError: 'N'"]


def test_pdf_parse_policy_document_job_creates_version_and_elements(tmp_path: Path) -> None:
    pdf_path = tmp_path / "policy.pdf"
    create_sample_pdf(pdf_path)
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)

    with client:
        headers = auth_headers(client)
        upload_response = client.post(
            "/api/files/upload",
            headers=headers,
            files={"file": ("policy.pdf", pdf_path.read_bytes(), "application/pdf")},
            data={"source_url": "https://example.com/policy.pdf"},
        )
        source_file_id = upload_response.json()["file_id"]
        job_response = client.post(
            "/api/jobs",
            headers=headers,
            json={
                "job_type": "parse_policy_document",
                "target_type": "source_file",
                "target_id": source_file_id,
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
    assert detail_response.json()["result_json"]["parser_type"] == "pdf_text"
    assert elements_response.status_code == 200
    assert elements_response.json()["total"] >= 4
    assert any(item["page_no"] == 1 for item in elements_response.json()["items"])
    assert any(item["bbox_json"] for item in elements_response.json()["items"])

    with SessionLocal() as db:
        source_file = db.get(SourceFile, UUID(source_file_id))
        version = db.get(PolicyDocumentVersion, UUID(version_id))
        job = db.get(IngestionJob, job_id)

    assert source_file is not None
    assert source_file.parse_status == "parsed"
    assert version is not None
    assert version.parser_type == "pdf_text"
    assert version.parse_json["extractor_mode"] == "layout"
    assert not version.parse_json["agent_refine_enabled"]
    assert job is not None
    assert job.progress_percent == 100
