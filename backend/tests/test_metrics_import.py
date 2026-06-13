from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import UUID

from openpyxl import Workbook

from app.db.models.dataset import Metric, MetricValue
from app.db.models.document import SourceFile
from app.db.models.ingestion_job import IngestionJob
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


LONG_METRICS_CSV = """indicator_code,indicator_name,domain,region_code,region_name,stat_year,value_numeric,unit,source,source_url,data_version
gdp_total,地区生产总值,economy,110000,北京市,2023,43760.7,亿元,北京市2023年国民经济和社会发展统计公报,https://example.com/2023,bulletin
gdp_total,地区生产总值,economy,110000,北京市,2024,49843.1,亿元,北京市2024年国民经济和社会发展统计公报,https://example.com/2024,bulletin
resident_population,常住人口,population,110000,北京市,2023,2185.8,万人,北京市2023年国民经济和社会发展统计公报,https://example.com/2023,bulletin
resident_population,常住人口,population,110000,北京市,2024,2183.2,万人,北京市2024年国民经济和社会发展统计公报,https://example.com/2024,bulletin
"""


def test_import_metric_values_from_long_csv_and_reuse_existing_rows(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)

    with client:
        headers = auth_headers(client)
        source_file_id = upload_file(
            client,
            headers=headers,
            file_name="metrics-long.csv",
            content=LONG_METRICS_CSV.encode("utf-8"),
            media_type="text/csv",
        )
        job_id = create_import_job(client, headers=headers, source_file_id=source_file_id)
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            first_result = db.get(IngestionJob, job_id).result_json

        second_job_id = create_import_job(client, headers=headers, source_file_id=source_file_id)
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            second_result = db.get(IngestionJob, second_job_id).result_json

        metrics_response = client.get("/api/metrics?keyword=常住人口", headers=headers)
        population_metric = metrics_response.json()["items"][0]
        values_response = client.get(f"/api/metrics/{population_metric['id']}/values", headers=headers)

    assert first_result["input_format"] == "long"
    assert first_result["metrics_created"] == 2
    assert first_result["metrics_updated"] == 0
    assert first_result["values_created"] == 4
    assert first_result["values_updated"] == 0
    assert second_result["metrics_created"] == 0
    assert second_result["metrics_updated"] == 2
    assert second_result["values_created"] == 0
    assert second_result["values_updated"] == 4

    assert metrics_response.status_code == 200
    assert metrics_response.json()["total"] == 1
    assert population_metric["indicator_code"] == "resident_population"
    assert population_metric["domain"] == "population"

    assert values_response.status_code == 200
    values = values_response.json()["items"]
    assert [value["stat_year"] for value in values] == [2023, 2024]
    assert values[-1]["value_numeric"] == 2183.2
    assert values[-1]["source_url"] == "https://example.com/2024"

    with SessionLocal() as db:
        assert db.query(Metric).count() == 2
        assert db.query(MetricValue).count() == 4
        assert all(source_file.parse_status == "parsed" for source_file in db.query(SourceFile).all())


def test_import_metric_values_from_wide_xlsx(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    workbook_bytes = make_xlsx(
        headers=["年份", "GDP", "常住人口"],
        rows=[[2024, 49843.1, 2183.2], [2025, 51000.0, 2180.0]],
    )

    with client:
        headers = auth_headers(client)
        source_file_id = upload_file(
            client,
            headers=headers,
            file_name="metrics-wide.xlsx",
            content=workbook_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        job_id = create_import_job(
            client,
            headers=headers,
            source_file_id=source_file_id,
            payload={
                "format": "wide",
                "default_region_code": "110000",
                "default_region_name": "北京市",
                "default_data_version": "wide-sample",
                "default_source": "宽表测试数据",
                "default_source_url": "https://example.com/wide",
            },
        )
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            result = db.get(IngestionJob, job_id).result_json

        gdp_response = client.get("/api/metrics?keyword=GDP", headers=headers)
        gdp_metric = gdp_response.json()["items"][0]
        values_response = client.get(
            f"/api/metrics/{gdp_metric['id']}/values?stat_year_from=2025",
            headers=headers,
        )

    assert result["input_format"] == "wide"
    assert result["source_rows"] == 2
    assert result["metric_rows"] == 4
    assert result["metrics_created"] == 2
    assert result["values_created"] == 4

    assert gdp_response.status_code == 200
    assert gdp_metric["indicator_code"] == "gdp_total"
    assert gdp_metric["unit"] == "亿元"

    assert values_response.status_code == 200
    assert values_response.json()["total"] == 1
    value = values_response.json()["items"][0]
    assert value["stat_year"] == 2025
    assert value["value_numeric"] == 51000.0
    assert value["data_version"] == "wide-sample"
    assert value["source_url"] == "https://example.com/wide"


def upload_file(
    client,
    *,
    headers: dict[str, str],
    file_name: str,
    content: bytes,
    media_type: str,
) -> str:
    response = client.post(
        "/api/files/upload",
        headers=headers,
        files={"file": (file_name, content, media_type)},
    )
    assert response.status_code == 201
    return response.json()["file_id"]


def create_import_job(
    client,
    *,
    headers: dict[str, str],
    source_file_id: str,
    payload: dict | None = None,
) -> UUID:
    request_payload = {"source_file_id": source_file_id}
    if payload:
        request_payload.update(payload)
    response = client.post("/api/metrics/import", headers=headers, json=request_payload)
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    return UUID(response.json()["job_id"])


def make_xlsx(*, headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
