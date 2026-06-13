from __future__ import annotations

from uuid import uuid4

import pytest

from app.llm.embedding_provider import EmbeddingProviderError
from app.llm.provider import LLMProviderRetryableError
from app.qa.schemas import QaResponse
from tests.helpers import auth_headers, make_test_client


class FakeApiOrchestrator:
    async def ask(self, *, question: str, user_id, request_id: str, current_date=None) -> QaResponse:
        _ = question, user_id, current_date
        return QaResponse(
            trace_id=uuid4(),
            route_type="POLICY_QA",
            answer="公共数据开放应依法有序推进。",
            citations=[],
            sql=None,
            chart=None,
            request_id=request_id,
        )


class FailingApiOrchestrator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def ask(self, **kwargs) -> QaResponse:
        _ = kwargs
        raise self.error


def test_qa_ask_requires_auth() -> None:
    client, _ = make_test_client()

    with client:
        response = client.post("/api/qa/ask", json={"question": "公共数据开放政策是什么？"})

    assert response.status_code == 401


def test_qa_ask_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = make_test_client()

    def fake_build_orchestrator(**kwargs):
        _ = kwargs
        return FakeApiOrchestrator()

    monkeypatch.setattr("app.api.v1.qa.build_orchestrator", fake_build_orchestrator)

    with client:
        headers = auth_headers(client)
        response = client.post(
            "/api/qa/ask",
            headers={**headers, "X-Request-ID": "qa-request-id"},
            json={"question": "公共数据开放政策是什么？", "options": {"return_trace": True}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "qa-request-id"
    assert payload["trace_id"]
    assert payload["route_type"] == "POLICY_QA"
    assert payload["answer"] == "公共数据开放应依法有序推进。"


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (EmbeddingProviderError("connection refused"), "Embedding 服务暂不可用，请稍后重试。"),
        (LLMProviderRetryableError("timeout"), "大模型服务暂不可用，请稍后重试。"),
    ],
)
def test_qa_ask_maps_provider_failures_to_503(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_message: str,
) -> None:
    client, _ = make_test_client()

    monkeypatch.setattr(
        "app.api.v1.qa.build_orchestrator",
        lambda **_: FailingApiOrchestrator(error),
    )

    with client:
        headers = auth_headers(client)
        response = client.post(
            "/api/qa/ask",
            headers=headers,
            json={"question": "公共数据开放政策是什么？"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == expected_message
