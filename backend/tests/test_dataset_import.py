from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import UUID

from openpyxl import Workbook

from app.db.models.dataset import OpenDataset, OpenDatasetField
from app.db.models.document import SourceFile
from app.db.models.ingestion_job import IngestionJob
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once
from tests.helpers import auth_headers, make_test_client, make_test_settings


CATALOG_CSV = """dataset_name,category,department,description,open_type,update_date,download_count,api_count,source_platform,source_url,custom_note
养老机构及养老驿站基础数据,民政服务,北京市民政局,北京市养老机构和养老驿站基础信息,无条件开放,2026-05-29,0,1,北京市公共数据开放平台,https://data.example.gov.cn/elderly,重点样例
北京市公共数据开放平台目录,公共数据目录,北京市经济和信息化局,平台开放数据目录与数据接口概览,无条件开放,2026-05-29,4457,4457,北京市公共数据开放平台,https://data.example.gov.cn/catalog,
"""

FIELDS_CSV = """dataset_name,field_name,field_type,description,example_value,is_dimension,is_measure
养老机构及养老驿站基础数据,机构名称,text,养老机构或养老驿站名称,某养老服务驿站,true,false
养老机构及养老驿站基础数据,所在区,text,机构所在行政区,海淀区,true,false
北京市公共数据开放平台目录,api_count,integer,数据集关联的数据接口数量,1,false,true
不存在的数据集,孤立字段,text,不会导入,示例,true,false
"""


def test_import_open_datasets_from_csv_and_reuse_existing_rows(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)

    with client:
        headers = auth_headers(client)
        catalog_file_id = upload_file(
            client,
            headers=headers,
            file_name="dataset-catalog.csv",
            content=CATALOG_CSV.encode("utf-8"),
            media_type="text/csv",
        )
        fields_file_id = upload_file(
            client,
            headers=headers,
            file_name="dataset-fields.csv",
            content=FIELDS_CSV.encode("utf-8"),
            media_type="text/csv",
        )

        job_id = create_import_job(
            client,
            headers=headers,
            catalog_file_id=catalog_file_id,
            fields_file_id=fields_file_id,
        )
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            first_result = db.get(IngestionJob, job_id).result_json

        second_job_id = create_import_job(
            client,
            headers=headers,
            catalog_file_id=catalog_file_id,
            fields_file_id=fields_file_id,
        )
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            second_result = db.get(IngestionJob, second_job_id).result_json

        list_response = client.get("/api/datasets", headers=headers)
        items = list_response.json()["items"]
        detail_response = client.get(f"/api/datasets/{items[0]['id']}", headers=headers)

    assert first_result["catalog_rows"] == 2
    assert first_result["field_rows"] == 4
    assert first_result["datasets_created"] == 2
    assert first_result["fields_created"] == 3
    assert first_result["field_rows_skipped"] == 1
    assert second_result["datasets_created"] == 0
    assert second_result["datasets_updated"] == 2
    assert second_result["fields_created"] == 0
    assert second_result["fields_updated"] == 3

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 2
    catalog_item = next(item for item in items if item["name"] == "北京市公共数据开放平台目录")
    assert catalog_item["open_type"] == "无条件开放"
    assert catalog_item["update_date"] == "2026-05-29"
    assert catalog_item["download_count"] == 4457
    assert catalog_item["api_count"] == 4457

    assert detail_response.status_code == 200
    assert "fields" in detail_response.json()

    with SessionLocal() as db:
        datasets = db.query(OpenDataset).all()
        fields = db.query(OpenDatasetField).all()
        source_files = db.query(SourceFile).all()

    assert len(datasets) == 2
    assert len(fields) == 3
    assert all(source_file.parse_status == "parsed" for source_file in source_files)
    elderly = next(dataset for dataset in datasets if dataset.name == "养老机构及养老驿站基础数据")
    assert elderly.metadata_json["custom_note"] == "重点样例"


def test_import_open_datasets_from_xlsx(tmp_path: Path) -> None:
    client, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)
    workbook_bytes = make_xlsx(
        headers=[
            "dataset_name",
            "category",
            "department",
            "description",
            "open_type",
            "update_date",
            "download_count",
            "api_count",
            "source_platform",
            "source_url",
        ],
        rows=[
            [
                "气象专题开放数据",
                "气象环境",
                "北京市气象部门",
                "气象专题开放数据",
                "无条件开放",
                "2023-01-01",
                0,
                1,
                "北京市公共数据开放平台",
                "https://data.example.gov.cn/weather",
            ]
        ],
    )

    with client:
        headers = auth_headers(client)
        catalog_file_id = upload_file(
            client,
            headers=headers,
            file_name="dataset-catalog.xlsx",
            content=workbook_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        job_id = create_import_job(client, headers=headers, catalog_file_id=catalog_file_id)
        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            result = db.get(IngestionJob, job_id).result_json

        list_response = client.get("/api/datasets?keyword=气象", headers=headers)

    assert result["datasets_created"] == 1
    assert result["fields_created"] == 0
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["items"][0]["name"] == "气象专题开放数据"


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
    catalog_file_id: str,
    fields_file_id: str | None = None,
) -> UUID:
    payload = {"catalog_source_file_id": catalog_file_id}
    if fields_file_id is not None:
        payload["fields_source_file_id"] = fields_file_id
    response = client.post("/api/datasets/import", headers=headers, json=payload)
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
