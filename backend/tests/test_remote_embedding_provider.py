from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.ingestion.handlers import build_embedding_provider
from app.llm.embedding_provider import (
    EmbeddingProviderError,
    RemoteHttpEmbeddingProvider,
    format_query,
    resize_embedding,
)


def test_openai_compatible_provider_sends_batch_and_orders_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer test-key"
        assert payload == {
            "model": "BAAI/bge-small-zh-v1.5",
            "input": ["问题", "政策文本"],
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = RemoteHttpEmbeddingProvider(
        model_name="BAAI/bge-small-zh-v1.5",
        embedding_dim=3,
        endpoint_url="http://embedding-server:8080/v1/embeddings",
        api_key="test-key",
        client=client,
    )

    assert provider.embed_documents(["问题", "政策文本"]) == [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]


def test_tei_provider_sends_normalize_flag_and_accepts_vector_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "inputs": ["公共数据"],
            "normalize": True,
        }
        return httpx.Response(200, json=[[0.1, 0.2]])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = RemoteHttpEmbeddingProvider(
        model_name="BAAI/bge-small-zh-v1.5",
        embedding_dim=2,
        endpoint_url="http://embedding-server:8080/embed",
        api_format="tei",
        client=client,
    )

    assert provider.embed_query("公共数据") == [0.1, 0.2]


def test_remote_provider_rejects_dimension_mismatch() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.1]}]},
            )
        )
    )
    provider = RemoteHttpEmbeddingProvider(
        model_name="test-model",
        embedding_dim=2,
        endpoint_url="http://embedding-server:8080/v1/embeddings",
        client=client,
    )

    with pytest.raises(EmbeddingProviderError, match="Embedding dim mismatch"):
        provider.embed_query("问题")


def test_openai_compatible_provider_requires_stable_indexes() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={"data": [{"embedding": [0.1, 0.2]}]},
            )
        )
    )
    provider = RemoteHttpEmbeddingProvider(
        model_name="test-model",
        embedding_dim=2,
        endpoint_url="http://embedding-server:8080/v1/embeddings",
        client=client,
    )

    with pytest.raises(EmbeddingProviderError, match="integer indexes"):
        provider.embed_query("问题")


def test_remote_provider_maps_http_errors() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, json={"detail": "model loading"})
        )
    )
    provider = RemoteHttpEmbeddingProvider(
        model_name="test-model",
        embedding_dim=2,
        endpoint_url="http://embedding-server:8080/v1/embeddings",
        client=client,
    )

    with pytest.raises(EmbeddingProviderError, match="HTTP 503"):
        provider.embed_query("问题")


def test_remote_provider_disables_environment_proxy_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_options: dict[str, object] = {}

    class StubClient:
        def __init__(self, **kwargs: object) -> None:
            client_options.update(kwargs)

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: object) -> httpx.Response:
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]},
            )

    monkeypatch.setattr(httpx, "Client", StubClient)
    provider = RemoteHttpEmbeddingProvider(
        model_name="test-model",
        embedding_dim=2,
        endpoint_url="http://embedding-server:8080/v1/embeddings",
    )

    assert provider.embed_query("问题") == [0.1, 0.2]
    assert client_options["trust_env"] is False


def test_embedding_provider_factory_builds_remote_provider() -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        readonly_database_url="sqlite+pysqlite:///:readonly:",
        deepseek_api_key="test-key",
        jwt_secret_key="test-secret-at-least-32-bytes-long",
        embedding_provider="remote_http",
        embedding_remote_url="http://embedding-server:8080/v1/embeddings",
        embedding_remote_api_key="embedding-key",
    )

    provider = build_embedding_provider(
        settings,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
    )

    assert isinstance(provider, RemoteHttpEmbeddingProvider)
    assert provider.endpoint_url == settings.embedding_remote_url
    assert provider.api_key == "embedding-key"
    assert provider.trust_env is False
    assert provider.query_instruction == settings.embedding_query_instruction


def test_remote_provider_applies_instruction_only_to_query() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    provider = RemoteHttpEmbeddingProvider(
        model_name="Qwen/Qwen3-Embedding-4B",
        embedding_dim=2,
        endpoint_url="http://embedding-server:8080/v1/embeddings",
        query_instruction="Retrieve government statistics.",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.embed_query("浙江各市 GDP")
    provider.embed_documents(["杭州市生产总值 20059 亿元"])

    assert requests[0]["input"] == [
        "Instruct: Retrieve government statistics.\nQuery:浙江各市 GDP"
    ]
    assert requests[1]["input"] == ["杭州市生产总值 20059 亿元"]


def test_resize_embedding_truncates_mrl_vector_and_normalizes() -> None:
    vector = resize_embedding([3.0, 4.0, 12.0], target_dim=2, normalize=True)

    assert vector == pytest.approx([0.6, 0.8])
    assert format_query("问题", "  检索政策  ") == "Instruct: 检索政策\nQuery:问题"
