from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from app.llm.contracts import ExtractedEntities, NormalizedTimeRange, QuestionRoute
from app.llm.provider import LLMJsonResult
from app.qa.router import QuestionRouter, infer_normalized_time_range


class FakeQuestionRouterProvider:
    def __init__(self, route: QuestionRoute) -> None:
        self.route = route
        self.calls: list[dict[str, Any]] = []

    async def generate_json(self, **kwargs) -> LLMJsonResult[QuestionRoute]:
        self.calls.append(kwargs)
        return LLMJsonResult(
            parsed=self.route,
            raw_text_preview=self.route.model_dump_json(),
            token_usage_json={"total_tokens": 42},
            cost_json={"currency": "CNY", "estimated": None},
            latency_ms=12,
            retry_count=0,
            model_name="deepseek-v4-pro",
            prompt_name=kwargs["prompt_name"],
            prompt_version=kwargs["prompt_version"],
            purpose=kwargs["purpose"],
        )


@pytest.mark.asyncio
async def test_question_router_calls_router_prompt_and_enriches_recent_time_range() -> None:
    provider = FakeQuestionRouterProvider(
        QuestionRoute(
            route_type="DATA_QA",
            needs_policy_evidence=False,
            needs_data_analysis=True,
            confidence=0.88,
            reason="用户询问人口结构化数据。",
            extracted_entities=ExtractedEntities(region="北京市", metrics=["常住人口"]),
        )
    )
    router = QuestionRouter(provider=provider)

    result = await router.route(
        question="北京市近五年常住人口变化如何？",
        current_date=date(2026, 6, 4),
    )

    assert result.parsed.route_type == "DATA_QA"
    assert result.parsed.extracted_entities.normalized_time_range == NormalizedTimeRange(
        start_year=2022,
        end_year=2026,
        grain="year",
        source_text="近五年",
        confidence=0.85,
    )
    assert provider.calls[0]["purpose"] == "question_router"
    assert provider.calls[0]["prompt_name"] == "router"
    assert provider.calls[0]["prompt_version"] == "v1.1"
    assert provider.calls[0]["response_model"] is QuestionRoute
    assert "北京市近五年常住人口变化如何？" in provider.calls[0]["user_prompt"]
    assert "JSON object" in provider.calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_question_router_overrides_incorrect_llm_relative_time_range() -> None:
    llm_time_range = NormalizedTimeRange(
        start_year=2020,
        end_year=2024,
        grain="year",
        source_text="近五年",
        confidence=0.91,
    )
    provider = FakeQuestionRouterProvider(
        QuestionRoute(
            route_type="DATA_QA",
            needs_policy_evidence=False,
            needs_data_analysis=True,
            confidence=0.9,
            reason="用户询问 GDP。",
            extracted_entities=ExtractedEntities(
                region="北京市",
                time_range="近五年",
                normalized_time_range=llm_time_range,
                metrics=["GDP"],
            ),
        )
    )

    result = await QuestionRouter(provider=provider).route(
        question="北京近五年 GDP 变化",
        current_date=date(2026, 6, 4),
    )

    assert result.parsed.extracted_entities.normalized_time_range == NormalizedTimeRange(
        start_year=2022,
        end_year=2026,
        grain="year",
        source_text="近五年",
        confidence=0.85,
    )


def test_infer_normalized_time_range_handles_explicit_year_range_and_relative_terms() -> None:
    current_date = date(2026, 6, 4)

    explicit_range = infer_normalized_time_range(
        question="北京 2020 到 2024 年 GDP 变化",
        current_date=current_date,
    )
    last_year = infer_normalized_time_range(question="去年常住人口是多少？", current_date=current_date)
    single_year = infer_normalized_time_range(question="2024 年 GDP 是多少？", current_date=current_date)

    assert explicit_range == NormalizedTimeRange(
        start_year=2020,
        end_year=2024,
        grain="year",
        source_text="2020 到 2024 年",
        confidence=0.95,
    )
    assert last_year.start_year == 2025
    assert last_year.end_year == 2025
    assert last_year.source_text == "去年"
    assert single_year.start_year == 2024
    assert single_year.end_year == 2024


def test_question_route_rejects_invalid_route_type() -> None:
    with pytest.raises(ValidationError):
        QuestionRoute.model_validate(
            {
                "route_type": "BAD",
                "needs_policy_evidence": False,
                "needs_data_analysis": False,
                "confidence": 0.4,
                "reason": "invalid",
                "extracted_entities": {},
            }
        )


@pytest.mark.asyncio
async def test_question_router_rejects_empty_question() -> None:
    provider = FakeQuestionRouterProvider(
        QuestionRoute(
            route_type="OTHER",
            needs_policy_evidence=False,
            needs_data_analysis=False,
            confidence=0.1,
            reason="empty",
        )
    )

    with pytest.raises(ValueError, match="question must not be empty"):
        await QuestionRouter(provider=provider).route(question="  ")
