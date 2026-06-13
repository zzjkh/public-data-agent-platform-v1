from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy.orm import Session

from app.analytics.sql_executor import SQLExecutionResult
from app.db.models.reporting import ReportingView, ReportingViewField
from app.db.models.semantic_metadata import SemanticMetadataEmbedding, SemanticMetadataItem
from app.db.models.trace import QaTrace, QaTraceSpan
from app.llm.contracts import (
    ChartSpec,
    ExtractedEntities,
    HybridAnswer,
    HybridPolicyCitation,
    PolicyCitation,
    QuestionRoute,
    RagAnswer,
    SqlGenerationResult,
    SqlResultExplanation,
)
from app.llm.provider import LLMJsonResult
from app.qa.orchestrator import QAOrchestrator
from app.semantic.reporting_metadata import REPORTING_VIEW_SEEDS, make_field_id
from tests.helpers import make_test_client, make_test_settings
from tests.test_policy_retriever import seed_policy_chunk
from tests.test_semantic_metadata import fake_vector


class FakeEmbeddingProvider:
    model_name = "fake-bge"
    embedding_dim = 3

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


class FakeQAProvider:
    async def generate_json(self, **kwargs) -> LLMJsonResult:
        response_model = kwargs["response_model"]
        user_prompt = kwargs["user_prompt"]
        if response_model is QuestionRoute:
            parsed = fake_route(user_prompt)
        elif response_model is RagAnswer:
            parsed = RagAnswer(
                answer="政策要求公共数据开放应依法有序推进，并保护个人信息。",
                evidence_sufficient=True,
                citations=[
                    PolicyCitation(
                        source_id="资料1",
                        source_title="公共数据开放管理办法",
                        source_url="https://example.com/policy",
                        section_path="第一章",
                        quote="公共数据开放应当依法有序推进。",
                    )
                ],
            )
        elif response_model is SqlGenerationResult:
            parsed = SqlGenerationResult(
                sql=(
                    "SELECT stat_year, value_numeric, unit, source, source_url "
                    "FROM reporting.vw_population_yearly "
                    "WHERE region_name = '北京市' AND stat_year BETWEEN 2022 AND 2026 "
                    "ORDER BY stat_year ASC LIMIT 100"
                ),
                reason="查询北京市常住人口年度趋势。",
                used_metadata_ids=[],
                confidence=0.9,
            )
        elif response_model is SqlResultExplanation:
            parsed = SqlResultExplanation(
                summary="北京市常住人口近年整体保持稳定。",
                key_findings=["2024 年常住人口为 2183.2 万人。"],
                data_sources=[{"title": "北京市统计公报", "source_url": "https://example.com/stat"}],
                caveat="当前数据仅覆盖 2023-2024 年。",
            )
        elif response_model is ChartSpec:
            parsed = ChartSpec(
                chart_type="line",
                x_field="stat_year",
                y_field="value_numeric",
                series_field=None,
                title="北京市常住人口趋势",
                reason="年份和数值字段适合折线图。",
            )
        elif response_model is HybridAnswer:
            parsed = HybridAnswer(
                answer="政策要求依法有序开放公共数据；数据上，北京市常住人口近年整体稳定。",
                policy_citations=[
                    HybridPolicyCitation(
                        source_title="公共数据开放管理办法",
                        source_url="https://example.com/policy",
                        section_path="第一章",
                        quote="公共数据开放应当依法有序推进。",
                    )
                ],
                data_sources=[{"title": "北京市统计公报", "source_url": "https://example.com/stat"}],
                used_sql=True,
                used_policy_evidence=True,
            )
        else:  # pragma: no cover - protects future contract additions.
            raise AssertionError(f"Unexpected response_model: {response_model}")

        return LLMJsonResult(
            parsed=parsed,
            raw_text_preview=parsed.model_dump_json(),
            token_usage_json={"total_tokens": 12},
            cost_json={"currency": "CNY", "estimated": None},
            latency_ms=5,
            retry_count=0,
            model_name="deepseek-v4-pro",
            prompt_name=kwargs["prompt_name"],
            prompt_version=kwargs["prompt_version"],
            purpose=kwargs["purpose"],
        )


class FakeSQLExecutor:
    def execute(self, guard_result) -> SQLExecutionResult:
        assert guard_result.valid
        assert guard_result.validated_sql
        return SQLExecutionResult(
            executed_sql=guard_result.validated_sql,
            columns=("stat_year", "value_numeric", "unit", "source", "source_url"),
            rows=(
                {
                    "stat_year": 2023,
                    "value_numeric": 2185.0,
                    "unit": "万人",
                    "source": "北京市统计公报",
                    "source_url": "https://example.com/stat",
                },
                {
                    "stat_year": 2024,
                    "value_numeric": 2183.2,
                    "unit": "万人",
                    "source": "北京市统计公报",
                    "source_url": "https://example.com/stat",
                },
            ),
            row_count=2,
            result_preview=(
                {
                    "stat_year": 2023,
                    "value_numeric": 2185.0,
                    "unit": "万人",
                    "source": "北京市统计公报",
                    "source_url": "https://example.com/stat",
                },
                {
                    "stat_year": 2024,
                    "value_numeric": 2183.2,
                    "unit": "万人",
                    "source": "北京市统计公报",
                    "source_url": "https://example.com/stat",
                },
            ),
            latency_ms=3,
        )


@pytest.mark.asyncio
async def test_qa_orchestrator_policy_qa_smoke() -> None:
    response, spans, trace = await run_qa_smoke("公共数据开放政策有哪些要求？")

    assert response.route_type == "POLICY_QA"
    assert response.answer.startswith("政策要求")
    assert response.citations[0].source_title == "公共数据开放管理办法"
    assert response.sql is None
    assert trace.status == "success"
    assert span_types(spans) == [
        "safety_guard",
        "router",
        "policy_retrieval",
        "answer_generation",
    ]


@pytest.mark.asyncio
async def test_qa_orchestrator_data_qa_smoke() -> None:
    response, spans, trace = await run_qa_smoke("北京市近五年常住人口变化如何？")

    assert response.route_type == "DATA_QA"
    assert response.sql is not None
    assert response.sql.row_count == 2
    assert response.chart is not None
    assert response.chart.chart_type == "line"
    assert "提示：当前数据仅覆盖 2023-2024 年。" in response.answer
    assert trace.status == "success"
    assert {
        "router",
        "semantic_retrieval",
        "sql_generation",
        "sql_guard",
        "sql_execution",
        "answer_generation",
        "chart_generation",
    }.issubset(set(span_types(spans)))


@pytest.mark.asyncio
async def test_qa_orchestrator_hybrid_qa_smoke() -> None:
    response, spans, trace = await run_qa_smoke("结合公共数据开放政策，分析北京市常住人口近年变化。")

    assert response.route_type == "HYBRID_QA"
    assert "政策" in response.answer
    assert response.sql is not None
    assert response.chart is not None
    assert {citation.type for citation in response.citations} == {"policy", "data"}
    assert trace.status == "success"
    assert span_types(spans).count("answer_generation") == 3
    policy_span = next(span for span in spans if span.span_type == "policy_retrieval")
    assert policy_span.input_json["query"] == (
        "公共数据开放 公共数据资源 个人信息保护 个人信息 个人隐私 数据安全 分类分级"
    )
    assert policy_span.input_json["original_question"].startswith("结合公共数据开放政策")
    assert policy_span.input_json["retrieval_strategy"][0] == "dense_vector"
    assert policy_span.input_json["embedding_dim"] == 3
    assert policy_span.input_json["raw_query_vector_recorded"] is False
    assert "dense_score" in policy_span.output_json["chunks"][0]


@pytest.mark.asyncio
async def test_data_retrieval_trace_explains_vector_and_keyword_sources() -> None:
    _, spans, _ = await run_qa_smoke("北京市近五年常住人口变化如何？")

    semantic_span = next(span for span in spans if span.span_type == "semantic_retrieval")
    assert semantic_span.input_json["retrieval_strategy"] == [
        "dense_vector",
        "keyword",
        "fulltext",
        "rule_rerank",
    ]
    assert semantic_span.input_json["embedding_model"] == "fake-bge"
    assert semantic_span.input_json["embedding_version"] == "v1"
    assert semantic_span.input_json["embedding_dim"] == 3
    assert semantic_span.output_json["source_counts"]["dense"] > 0
    assert "dense_score" in semantic_span.output_json["items"][0]
    assert "keyword_score" in semantic_span.output_json["items"][0]


@pytest.mark.asyncio
async def test_qa_orchestrator_blocks_internal_asset_enumeration_before_llm() -> None:
    response, spans, trace = await run_qa_smoke("数据库里有多少条关于人口信息的数据？")

    assert response.route_type == "OTHER"
    assert "无法提供系统数据库内部" in response.answer
    assert response.sql is None
    assert response.chart is None
    assert trace.status == "refused"
    assert span_types(spans) == ["safety_guard"]
    assert spans[0].output_json["code"] == "INTERNAL_ASSET_ENUMERATION"


async def run_qa_smoke(question: str):
    _, SessionLocal = make_test_client()
    settings = make_test_settings()
    settings.embedding_model = "fake-bge"
    settings.embedding_dim = 3
    settings.embedding_version = "v1"

    with SessionLocal() as db:
        seed_qa_sources(db)
        response = await QAOrchestrator(
            db,
            settings=settings,
            provider=FakeQAProvider(),
            embedding_provider=FakeEmbeddingProvider(),
            sql_executor=FakeSQLExecutor(),
        ).ask(
            question=question,
            user_id=None,
            request_id="test-request-id",
            current_date=date(2026, 6, 5),
        )
        trace = db.get(QaTrace, response.trace_id)
        spans = db.query(QaTraceSpan).filter(QaTraceSpan.trace_id == response.trace_id).order_by(
            QaTraceSpan.span_order
        ).all()
    return response, spans, trace


def seed_qa_sources(db: Session) -> None:
    seed_policy_chunk(
        db,
        title="公共数据开放管理办法",
        chunk_text="公共数据开放应当依法有序推进。",
        vector=[1.0, 0.0, 0.0],
    )
    seed_reporting_metadata(db)
    db.commit()


def seed_reporting_metadata(db: Session) -> None:
    view_seed = next(seed for seed in REPORTING_VIEW_SEEDS if seed.view_name == "vw_population_yearly")
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

    item = SemanticMetadataItem(
        metadata_type="metric",
        name="常住人口",
        aliases_json=["人口规模"],
        description="反映北京市年度常住人口规模。",
        related_table="reporting.vw_population_yearly",
        related_field="value_numeric",
        unit="万人",
        time_grain="annual",
        embedding_text="常住人口 人口规模 reporting.vw_population_yearly value_numeric",
        search_text="常住人口 人口规模 reporting.vw_population_yearly value_numeric",
    )
    db.add(item)
    db.flush()
    db.add(
        SemanticMetadataEmbedding(
            metadata_item_id=item.id,
            embedding_model="fake-bge",
            embedding_dim=3,
            embedding_version="v1",
            embedding=fake_vector(item.embedding_text, 3),
        )
    )
    db.flush()


def fake_route(user_prompt: str) -> QuestionRoute:
    question = user_prompt.split("用户问题：", 1)[-1].split("规则：", 1)[0]
    if "结合" in question:
        route_type = "HYBRID_QA"
    elif "人口" in question or "GDP" in question:
        route_type = "DATA_QA"
    elif "政策" in question or "开放" in question:
        route_type = "POLICY_QA"
    else:
        route_type = "OTHER"
    return QuestionRoute(
        route_type=route_type,
        needs_policy_evidence=route_type in {"POLICY_QA", "HYBRID_QA"},
        needs_data_analysis=route_type in {"DATA_QA", "HYBRID_QA"},
        confidence=0.9,
        reason=f"路由到 {route_type}",
        extracted_entities=ExtractedEntities(
            policy_topics=(
                ["公共数据开放", "个人信息保护", "数据安全"]
                if route_type == "HYBRID_QA"
                else []
            )
        ),
    )


def span_types(spans: list[QaTraceSpan]) -> list[str]:
    return [span.span_type for span in spans]
