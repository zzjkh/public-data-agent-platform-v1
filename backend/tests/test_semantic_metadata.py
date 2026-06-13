from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.dataset import Metric, OpenDataset
from app.db.models.ingestion_job import IngestionJob
from app.db.models.reporting import ReportingView, ReportingViewField
from app.db.models.semantic_metadata import SemanticMetadataEmbedding, SemanticMetadataItem
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once
from app.semantic.reporting_metadata import REPORTING_VIEW_SEEDS, make_field_id
from app.semantic.retriever import SemanticMetadataRetriever
from app.semantic.service import SemanticMetadataService
from tests.helpers import auth_headers, make_test_client, make_test_settings


class FakeEmbeddingProvider:
    def __init__(self, *, embedding_dim: int = 8) -> None:
        self.model_name = "fake-semantic"
        self.embedding_dim = embedding_dim

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [fake_vector(text, self.embedding_dim) for text in texts]


def test_rebuild_semantic_metadata_and_retrieve_with_fake_embeddings() -> None:
    client, SessionLocal = make_test_client()
    _ = client
    provider = FakeEmbeddingProvider(embedding_dim=8)

    with SessionLocal() as db:
        seed_semantic_sources(db)
        service = SemanticMetadataService(db, make_test_settings())
        first_result = service.rebuild_metadata(
            metadata_types=None,
            provider=provider,
            embedding_model=provider.model_name,
            embedding_dim=provider.embedding_dim,
            embedding_version="test-v1",
            batch_size=4,
            max_retries=0,
        )
        db.commit()

        second_result = service.rebuild_metadata(
            metadata_types=None,
            provider=provider,
            embedding_model=provider.model_name,
            embedding_dim=provider.embedding_dim,
            embedding_version="test-v1",
            batch_size=4,
            max_retries=0,
        )
        db.commit()

        retrieval = SemanticMetadataRetriever(db).retrieve(
            query="北京市近五年人口规模变化",
            embedding_provider=provider,
            embedding_model=provider.model_name,
            embedding_version="test-v1",
            top_k=5,
        )

        item_count = db.query(SemanticMetadataItem).count()
        embedding_count = db.query(SemanticMetadataEmbedding).count()
        metadata_types = {
            metadata_type
            for (metadata_type,) in db.query(SemanticMetadataItem.metadata_type).distinct().all()
        }

    assert first_result.items_created == first_result.item_count
    assert first_result.embeddings_created == first_result.item_count
    assert second_result.items_created == 0
    assert second_result.items_updated == 0
    assert second_result.embeddings_created == 0
    assert second_result.embeddings_reused == second_result.item_count
    assert item_count == embedding_count
    assert {"metric", "field", "sql_example", "business_rule"}.issubset(metadata_types)
    assert any("常住人口" in hit.item.search_text for hit in retrieval.items)
    assert any("reporting.vw_population_yearly" == hit.item.related_table for hit in retrieval.items)


def test_semantic_api_rebuild_list_and_search(monkeypatch) -> None:
    client, SessionLocal = make_test_client()
    settings = make_test_settings()

    def fake_build_embedding_provider(settings, *, embedding_model: str, embedding_dim: int):
        _ = settings, embedding_model
        return FakeEmbeddingProvider(embedding_dim=embedding_dim)

    monkeypatch.setattr("app.ingestion.handlers.build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr("app.api.v1.semantic.build_embedding_provider", fake_build_embedding_provider)

    with SessionLocal() as db:
        seed_semantic_sources(db)
        db.commit()

    with client:
        headers = auth_headers(client)
        response = client.post(
            "/api/semantic/rebuild",
            headers=headers,
            json={"types": ["metric", "field", "sql_example", "business_rule"]},
        )
        assert response.status_code == 201
        job_id = response.json()["job_id"]

        with SessionLocal() as db:
            run_worker_once(db=db, settings=settings, handlers=get_default_job_handlers(settings))
            job = db.get(IngestionJob, UUID(job_id))

        list_response = client.get("/api/semantic/items?metadata_type=metric", headers=headers)
        search_response = client.post(
            "/api/semantic/search",
            headers=headers,
            json={"query": "北京 GDP 变化", "top_k": 5},
        )

    assert job.status == "success"
    assert job.result_json["items_created"] > 0
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 2
    assert search_response.status_code == 200
    assert any("GDP" in hit["item"]["search_text"] for hit in search_response.json()["items"])


def seed_semantic_sources(db: Session) -> None:
    for view_seed in REPORTING_VIEW_SEEDS[:2]:
        view = ReportingView(
            id=view_seed.id,
            schema_name=view_seed.schema_name,
            view_name=view_seed.view_name,
            description=view_seed.description,
            enabled=True,
        )
        db.add(view)
        for field_seed in view_seed.fields:
            db.add(
                ReportingViewField(
                    id=make_field_id(view_seed, field_seed.field_name),
                    view_id=view.id,
                    field_name=field_seed.field_name,
                    field_type=field_seed.field_type,
                    description=field_seed.description,
                    is_dimension=field_seed.is_dimension,
                    is_measure=field_seed.is_measure,
                    allowed_filter=field_seed.allowed_filter,
                    allowed_group_by=field_seed.allowed_group_by,
                    example_value=field_seed.example_value,
                )
            )

    db.add_all(
        [
            Metric(
                indicator_code="resident_population",
                indicator_name="常住人口",
                domain="population",
                unit="万人",
                description="反映北京市年度常住人口规模。",
                aliases_json=["人口规模", "年末常住人口"],
            ),
            Metric(
                indicator_code="gdp_total",
                indicator_name="地区生产总值",
                domain="economy",
                unit="亿元",
                description="反映北京市年度经济总量。",
                aliases_json=["GDP", "经济总量"],
            ),
        ]
    )
    db.add(
        OpenDataset(
            name="北京市公共数据开放平台目录",
            description="平台开放数据目录与数据接口概览。",
            category="公共数据目录",
            department="北京市经济和信息化局",
            source_platform="北京市公共数据开放平台",
            source_url="https://data.example.gov.cn/catalog",
            open_type="无条件开放",
            update_date=date(2026, 5, 29),
            download_count=4457,
            api_count=4457,
            status="active",
        )
    )
    db.flush()


def fake_vector(text: str, dim: int) -> list[float]:
    features = [
        1.0 if any(keyword in text for keyword in ("人口", "常住", "population")) else 0.0,
        1.0 if any(keyword in text for keyword in ("GDP", "生产总值", "经济")) else 0.0,
        1.0 if any(keyword in text for keyword in ("数据集", "开放数据", "目录")) else 0.0,
        1.0 if any(keyword in text for keyword in ("字段", "value_numeric", "stat_year")) else 0.0,
        1.0 if any(keyword in text for keyword in ("SQL", "SELECT", "查询")) else 0.0,
        min(len(text) / 500.0, 1.0),
    ]
    if len(features) < dim:
        features.extend([0.0] * (dim - len(features)))
    return features[:dim]
