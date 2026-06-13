from __future__ import annotations

import json

import httpx
import pytest

from app.llm.contracts import QuestionRoute
from app.llm.provider import (
    DeepSeekLLMProvider,
    LLMProviderAuthError,
    LLMProviderPromptError,
    LLMProviderRetryableError,
    LLMProviderValidationError,
)
from tests.helpers import make_test_settings


VALID_ROUTE_PAYLOAD = {
    "route_type": "DATA_QA",
    "needs_policy_evidence": False,
    "needs_data_analysis": True,
    "confidence": 0.91,
    "reason": "用户询问结构化人口数据。",
    "extracted_entities": {
        "region": "北京市",
        "time_range": "近五年",
        "normalized_time_range": {
            "start_year": 2021,
            "end_year": 2025,
            "grain": "year",
            "source_text": "近五年",
            "confidence": 0.8,
        },
        "metrics": ["常住人口"],
        "policy_topics": [],
    },
}


@pytest.mark.asyncio
async def test_deepseek_provider_generates_validated_json() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(VALID_ROUTE_PAYLOAD)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekLLMProvider(make_test_settings(), client=client)

    result = await provider.generate_json(
        purpose="question_router",
        prompt_name="router",
        prompt_version="v1.0",
        system_prompt="你必须输出 JSON object。",
        user_prompt="请判断问题路由，并输出 JSON。",
        response_model=QuestionRoute,
    )

    assert result.parsed.route_type == "DATA_QA"
    assert result.parsed.confidence == 0.91
    assert result.token_usage_json["total_tokens"] == 140
    assert result.cost_json["estimated"] is None
    assert result.retry_count == 0
    assert requests[0]["model"] == "deepseek-v4-flash"
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["messages"][0]["role"] == "system"
    await provider.aclose()


@pytest.mark.asyncio
async def test_deepseek_provider_retries_once_after_pydantic_validation_failure() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"route_type": "BAD"}'}}]},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_ROUTE_PAYLOAD)}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekLLMProvider(make_test_settings(), client=client)

    result = await provider.generate_json(
        purpose="question_router",
        prompt_name="router",
        prompt_version="v1.0",
        system_prompt="输出 JSON object。",
        user_prompt="请输出 JSON。",
        response_model=QuestionRoute,
        max_retries=1,
    )

    assert result.parsed.route_type == "DATA_QA"
    assert result.retry_count == 1
    assert len(requests) == 2
    assert "Pydantic" in requests[1]["messages"][-1]["content"]
    await provider.aclose()


@pytest.mark.asyncio
async def test_deepseek_provider_raises_after_validation_retry_exhausted() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"route_type": "BAD"}'}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekLLMProvider(make_test_settings(), client=client)

    with pytest.raises(LLMProviderValidationError):
        await provider.generate_json(
            purpose="question_router",
            prompt_name="router",
            prompt_version="v1.0",
            system_prompt="输出 JSON object。",
            user_prompt="请输出 JSON。",
            response_model=QuestionRoute,
            max_retries=1,
        )
    await provider.aclose()


@pytest.mark.asyncio
async def test_deepseek_provider_maps_auth_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekLLMProvider(make_test_settings(), client=client)

    with pytest.raises(LLMProviderAuthError):
        await provider.generate_json(
            purpose="question_router",
            prompt_name="router",
            prompt_version="v1.0",
            system_prompt="输出 JSON object。",
            user_prompt="请输出 JSON。",
            response_model=QuestionRoute,
        )
    await provider.aclose()


@pytest.mark.asyncio
async def test_deepseek_provider_preserves_retryable_error_after_exhaustion() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(500, json={"error": {"message": "server error"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekLLMProvider(make_test_settings(), client=client)

    with pytest.raises(LLMProviderRetryableError):
        await provider.generate_json(
            purpose="question_router",
            prompt_name="router",
            prompt_version="v1.0",
            system_prompt="输出 JSON object。",
            user_prompt="请输出 JSON。",
            response_model=QuestionRoute,
            max_retries=1,
        )

    assert len(requests) == 2
    await provider.aclose()


@pytest.mark.asyncio
async def test_deepseek_provider_requires_json_instruction() -> None:
    provider = DeepSeekLLMProvider(make_test_settings())

    with pytest.raises(LLMProviderPromptError):
        await provider.generate_json(
            purpose="question_router",
            prompt_name="router",
            prompt_version="v1.0",
            system_prompt="你是路由器。",
            user_prompt="请判断问题。",
            response_model=QuestionRoute,
        )
    await provider.aclose()
