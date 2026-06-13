from __future__ import annotations

from typing import Any

import pytest

from app.analytics.sql_generator import (
    SQLGenerationError,
    SQLGenerator,
    contains_select_star,
    semantic_hit_from_item,
)
from app.db.models.reporting import ReportingView, ReportingViewField
from app.db.models.semantic_metadata import SemanticMetadataItem
from app.llm.contracts import NormalizedTimeRange, SqlGenerationResult
from app.llm.provider import LLMJsonResult
from app.semantic.reporting_metadata import REPORTING_VIEW_SEEDS, make_field_id
from tests.helpers import make_test_client


class FakeSQLGenerationProvider:
    def __init__(self, result: SqlGenerationResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def generate_json(self, **kwargs) -> LLMJsonResult[SqlGenerationResult]:
        self.calls.append(kwargs)
        return LLMJsonResult(
            parsed=self.result,
            raw_text_preview=self.result.model_dump_json(),
            token_usage_json={"total_tokens": 88},
            cost_json={"currency": "CNY", "estimated": None},
            latency_ms=20,
            retry_count=0,
            model_name="deepseek-v4-pro",
            prompt_name=kwargs["prompt_name"],
            prompt_version=kwargs["prompt_version"],
            purpose=kwargs["purpose"],
        )


@pytest.mark.asyncio
async def test_sql_generator_builds_candidate_schema_and_calls_llm() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        metadata = seed_sql_generation_metadata(db)
        metric = metadata["metric"]
        field = metadata["field"]
        sql_example = metadata["sql_example"]
        provider = FakeSQLGenerationProvider(
            SqlGenerationResult(
                sql=(
                    "SELECT stat_year, value_numeric, unit "
                    "FROM reporting.vw_gdp_yearly "
                    "WHERE region_name = '北京市' AND stat_year BETWEEN 2020 AND 2024 "
                    "ORDER BY stat_year ASC LIMIT 100"
                ),
                reason="选择 GDP 年度视图并按年份查询趋势。",
                used_metadata_ids=[str(metric.id), str(field.id), str(sql_example.id)],
                confidence=0.91,
            )
        )

        output = await SQLGenerator(db, provider=provider).generate(
            question="北京市 2020 到 2024 年 GDP 变化如何？",
            semantic_hits=[
                semantic_hit_from_item(metric, final_score=0.9),
                semantic_hit_from_item(field, final_score=0.8),
                semantic_hit_from_item(sql_example, final_score=0.7),
            ],
            normalized_time_range=NormalizedTimeRange(
                start_year=2020,
                end_year=2024,
                grain="year",
                source_text="2020 到 2024 年",
                confidence=0.95,
            ),
        )

    assert output.result.parsed.confidence == 0.91
    assert output.result.token_usage_json["total_tokens"] == 88
    assert "reporting.vw_gdp_yearly" in output.candidate_schema
    assert "value_numeric" in output.candidate_schema
    assert "年度地区生产总值趋势查询" in output.sql_examples_text
    assert '"start_year": 2020' in output.normalized_time_range_text

    call = provider.calls[0]
    assert call["purpose"] == "sql_generation"
    assert call["prompt_name"] == "sql_generation"
    assert call["prompt_version"] == "v1.1"
    assert call["response_model"] is SqlGenerationResult
    assert "reporting.vw_gdp_yearly" in call["user_prompt"]
    assert "2020" in call["user_prompt"]
    assert "2024" in call["user_prompt"]
    assert "SELECT *" in call["user_prompt"]


@pytest.mark.asyncio
async def test_sql_generator_rejects_select_star() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        metadata = seed_sql_generation_metadata(db)
        metric = metadata["metric"]
        provider = FakeSQLGenerationProvider(
            SqlGenerationResult(
                sql="SELECT * FROM reporting.vw_gdp_yearly LIMIT 100",
                reason="bad",
                used_metadata_ids=[str(metric.id)],
                confidence=0.2,
            )
        )

        with pytest.raises(SQLGenerationError, match="SELECT \\*"):
            await SQLGenerator(db, provider=provider).generate(
                question="北京 GDP",
                semantic_hits=[semantic_hit_from_item(metric)],
            )


@pytest.mark.asyncio
async def test_sql_generator_filters_unknown_metadata_id() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        metadata = seed_sql_generation_metadata(db)
        metric = metadata["metric"]
        provider = FakeSQLGenerationProvider(
            SqlGenerationResult(
                sql="SELECT stat_year FROM reporting.vw_gdp_yearly LIMIT 100",
                reason="bad metadata id",
                used_metadata_ids=["unknown"],
                confidence=0.7,
            )
        )

        output = await SQLGenerator(db, provider=provider).generate(
            question="北京 GDP",
            semantic_hits=[semantic_hit_from_item(metric)],
        )

    assert output.result.parsed.used_metadata_ids == []
    assert output.result.parsed.sql == "SELECT stat_year FROM reporting.vw_gdp_yearly LIMIT 100"


@pytest.mark.asyncio
async def test_sql_generator_rejects_missing_normalized_time_range_years() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        metadata = seed_sql_generation_metadata(db)
        metric = metadata["metric"]
        provider = FakeSQLGenerationProvider(
            SqlGenerationResult(
                sql="SELECT stat_year FROM reporting.vw_gdp_yearly LIMIT 100",
                reason="missing years",
                used_metadata_ids=[str(metric.id)],
                confidence=0.7,
            )
        )

        with pytest.raises(SQLGenerationError, match="normalized_time_range"):
            await SQLGenerator(db, provider=provider).generate(
                question="北京 2020 到 2024 年 GDP",
                semantic_hits=[semantic_hit_from_item(metric)],
                normalized_time_range=NormalizedTimeRange(
                    start_year=2020,
                    end_year=2024,
                    grain="year",
                    source_text="2020 到 2024 年",
                    confidence=0.95,
                ),
            )


@pytest.mark.asyncio
async def test_sql_generator_requires_candidate_reporting_view() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        item = SemanticMetadataItem(
            metadata_type="metric",
            name="测试指标",
            related_table="public.metric_values",
            related_field="value_numeric",
            embedding_text="测试",
            search_text="测试",
        )
        db.add(item)
        db.flush()
        provider = FakeSQLGenerationProvider(
            SqlGenerationResult(sql="SELECT 1 LIMIT 1", reason="bad", confidence=0.1)
        )

        with pytest.raises(SQLGenerationError, match="No candidate reporting views"):
            await SQLGenerator(db, provider=provider).generate(
                question="测试",
                semantic_hits=[semantic_hit_from_item(item)],
            )


def test_contains_select_star_detects_wildcard_projection() -> None:
    assert contains_select_star("SELECT * FROM reporting.vw_gdp_yearly")
    assert contains_select_star("SELECT g.* FROM reporting.vw_gdp_yearly g")
    assert not contains_select_star("SELECT stat_year, value_numeric FROM reporting.vw_gdp_yearly")


def seed_sql_generation_metadata(db) -> dict[str, SemanticMetadataItem]:
    gdp_view_seed = next(seed for seed in REPORTING_VIEW_SEEDS if seed.view_name == "vw_gdp_yearly")
    view = ReportingView(
        id=gdp_view_seed.id,
        schema_name=gdp_view_seed.schema_name,
        view_name=gdp_view_seed.view_name,
        description=gdp_view_seed.description,
        enabled=True,
    )
    db.add(view)
    for field_seed in gdp_view_seed.fields:
        db.add(
            ReportingViewField(
                id=make_field_id(gdp_view_seed, field_seed.field_name),
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

    metric = SemanticMetadataItem(
        metadata_type="metric",
        name="地区生产总值",
        aliases_json=["GDP", "经济总量"],
        description="反映北京市年度经济总量。",
        related_table="reporting.vw_gdp_yearly",
        related_field="value_numeric",
        unit="亿元",
        time_grain="annual",
        embedding_text="GDP 地区生产总值 reporting.vw_gdp_yearly value_numeric",
        search_text="GDP 地区生产总值 reporting.vw_gdp_yearly value_numeric",
    )
    field = SemanticMetadataItem(
        metadata_type="field",
        name="reporting.vw_gdp_yearly.value_numeric",
        description="指标数值。",
        related_table="reporting.vw_gdp_yearly",
        related_field="value_numeric",
        embedding_text="字段 value_numeric 指标数值",
        search_text="字段 value_numeric 指标数值",
    )
    sql_example = SemanticMetadataItem(
        metadata_type="sql_example",
        name="年度地区生产总值趋势查询",
        description="查询北京市年度 GDP 趋势。",
        related_table="reporting.vw_gdp_yearly",
        related_field="",
        sql_example=(
            "SELECT stat_year, value_numeric, unit "
            "FROM reporting.vw_gdp_yearly "
            "WHERE region_name = '北京市' "
            "ORDER BY stat_year ASC LIMIT 100"
        ),
        embedding_text="SQL 示例 GDP 趋势",
        search_text="SQL 示例 GDP 趋势",
    )
    db.add_all([metric, field, sql_example])
    db.flush()
    return {"metric": metric, "field": field, "sql_example": sql_example}
