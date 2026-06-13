from __future__ import annotations

from aiohttp.test_utils import TestClient, TestServer

from embedding_server.app import create_app
from embedding_server.config import ServerSettings


class FakeEngine:
    dimension = 3
    loaded = True

    def load(self) -> None:
        self.loaded = True

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[float(index), 0.5, 1.0] for index, _ in enumerate(texts)]


async def build_client(**overrides: object) -> TestClient:
    values = {
        "model_name": "Qwen/Qwen3-Embedding-4B",
        "model_path": "/models/Qwen3-Embedding-4B",
        "embedding_dim": 3,
        "device": "cuda:0",
        "api_key": "test-key",
        "max_batch_size": 2,
        "max_text_chars": 20,
    }
    values.update(overrides)
    app = create_app(
        settings=ServerSettings(**values),
        engine=FakeEngine(),
        load_model_on_startup=False,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_health_reports_model_state() -> None:
    client = await build_client()
    try:
        response = await client.get("/health")
        payload = await response.json()
        assert response.status == 200
        assert payload["ready"] is True
        assert payload["dimension"] == 3
    finally:
        await client.close()


async def test_embeddings_returns_openai_compatible_response() -> None:
    client = await build_client()
    try:
        response = await client.post(
            "/v1/embeddings",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "Qwen/Qwen3-Embedding-4B",
                "input": ["问题", "政策文本"],
                "encoding_format": "float",
            },
        )
        payload = await response.json()
        assert response.status == 200
        assert payload["data"] == [
            {"object": "embedding", "index": 0, "embedding": [0.0, 0.5, 1.0]},
            {"object": "embedding", "index": 1, "embedding": [1.0, 0.5, 1.0]},
        ]
    finally:
        await client.close()


async def test_embeddings_requires_api_key() -> None:
    client = await build_client()
    try:
        response = await client.post(
            "/v1/embeddings",
            json={"model": "Qwen/Qwen3-Embedding-4B", "input": ["问题"]},
        )
        assert response.status == 401
    finally:
        await client.close()


async def test_embeddings_rejects_wrong_model_and_oversized_batch() -> None:
    client = await build_client()
    headers = {"Authorization": "Bearer test-key"}
    try:
        wrong_model = await client.post(
            "/v1/embeddings",
            headers=headers,
            json={"model": "other-model", "input": ["问题"]},
        )
        oversized = await client.post(
            "/v1/embeddings",
            headers=headers,
            json={
                "model": "Qwen/Qwen3-Embedding-4B",
                "input": ["一", "二", "三"],
            },
        )
        assert wrong_model.status == 404
        assert oversized.status == 413
    finally:
        await client.close()
