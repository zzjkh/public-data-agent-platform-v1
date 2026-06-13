from __future__ import annotations

import math
from typing import Any, Literal, Protocol

import httpx


class EmbeddingProvider(Protocol):
    model_name: str
    embedding_dim: int

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class EmbeddingProviderError(RuntimeError):
    pass


class SentenceTransformerEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str,
        embedding_dim: int,
        normalize_embeddings: bool = True,
        device: str | None = None,
        query_instruction: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.embedding_dim = embedding_dim
        self.normalize_embeddings = normalize_embeddings
        self.device = device
        self.query_instruction = query_instruction
        self._model = None

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([format_query(text, self.query_instruction)])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load_model().encode(
            texts,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        result = [[float(value) for value in vector] for vector in vectors.tolist()]
        return [
            resize_embedding(
                vector,
                target_dim=self.embedding_dim,
                normalize=self.normalize_embeddings,
            )
            for vector in result
        ]

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingProviderError(
                "sentence-transformers is not installed. "
                "Run `uv sync --dev --extra embeddings` before building local embeddings."
            ) from exc

        kwargs = {"device": self.device} if self.device else {}
        try:
            self._model = SentenceTransformer(self.model_name, **kwargs)
        except Exception as exc:  # pragma: no cover - depends on local model download/cache.
            raise EmbeddingProviderError(f"Failed to load embedding model {self.model_name}: {exc}") from exc
        return self._model


class RemoteHttpEmbeddingProvider:
    def __init__(
        self,
        *,
        model_name: str,
        embedding_dim: int,
        endpoint_url: str,
        api_format: Literal["openai", "tei"] = "openai",
        api_key: str | None = None,
        timeout_seconds: int = 30,
        normalize_embeddings: bool = True,
        trust_env: bool = False,
        query_instruction: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model_name = model_name
        self.embedding_dim = embedding_dim
        self.endpoint_url = endpoint_url
        self.api_format = api_format
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.normalize_embeddings = normalize_embeddings
        self.trust_env = trust_env
        self.query_instruction = query_instruction
        self.client = client

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([format_query(text, self.query_instruction)])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = self._build_payload(texts)
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            if self.client is not None:
                response = self.client.post(self.endpoint_url, json=payload, headers=headers)
            else:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    trust_env=self.trust_env,
                ) as client:
                    response = client.post(self.endpoint_url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise EmbeddingProviderError(
                f"Remote embedding request failed with HTTP {exc.response.status_code}: {body}"
            ) from exc
        except httpx.RequestError as exc:
            raise EmbeddingProviderError(f"Remote embedding request failed: {exc}") from exc

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise EmbeddingProviderError("Remote embedding response is not valid JSON") from exc

        vectors = self._parse_vectors(response_payload)
        self._validate_vectors(vectors=vectors, expected_count=len(texts))
        return vectors

    def _build_payload(self, texts: list[str]) -> dict[str, Any]:
        if self.api_format == "openai":
            return {
                "model": self.model_name,
                "input": texts,
                "encoding_format": "float",
            }
        return {
            "inputs": texts,
            "normalize": self.normalize_embeddings,
        }

    def _parse_vectors(self, payload: Any) -> list[list[float]]:
        if self.api_format == "openai":
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise EmbeddingProviderError("OpenAI-compatible response must contain a data list")
            if not all(isinstance(item, dict) for item in payload["data"]):
                raise EmbeddingProviderError("OpenAI-compatible data items must be objects")
            try:
                indexes = [int(item["index"]) for item in payload["data"]]
            except (KeyError, TypeError, ValueError) as exc:
                raise EmbeddingProviderError(
                    "OpenAI-compatible data items must contain integer indexes"
                ) from exc
            if sorted(indexes) != list(range(len(payload["data"]))):
                raise EmbeddingProviderError(
                    "OpenAI-compatible response indexes must be unique and contiguous"
                )
            ordered = [
                item
                for _, item in sorted(
                    zip(indexes, payload["data"], strict=True),
                    key=lambda pair: pair[0],
                )
            ]
            raw_vectors = [item.get("embedding") for item in ordered]
        elif isinstance(payload, list):
            raw_vectors = payload
        elif isinstance(payload, dict) and isinstance(payload.get("embeddings"), list):
            raw_vectors = payload["embeddings"]
        else:
            raise EmbeddingProviderError("TEI response must be a vector list or contain embeddings")

        try:
            return [[float(value) for value in vector] for vector in raw_vectors]
        except (TypeError, ValueError) as exc:
            raise EmbeddingProviderError("Remote embedding response contains invalid vectors") from exc

    def _validate_vectors(self, *, vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise EmbeddingProviderError(
                f"Embedding count mismatch: expected {expected_count}, got {len(vectors)}"
            )
        for vector in vectors:
            if len(vector) != self.embedding_dim:
                raise EmbeddingProviderError(
                    f"Embedding dim mismatch: expected {self.embedding_dim}, got {len(vector)}"
                )


def format_query(text: str, instruction: str | None) -> str:
    normalized_instruction = (instruction or "").strip()
    if not normalized_instruction:
        return text
    return f"Instruct: {normalized_instruction}\nQuery:{text}"


def resize_embedding(vector: list[float], *, target_dim: int, normalize: bool) -> list[float]:
    if len(vector) < target_dim:
        raise EmbeddingProviderError(
            f"Embedding dim mismatch: expected at least {target_dim}, got {len(vector)}"
        )
    resized = vector[:target_dim]
    if not normalize:
        return resized
    norm = math.sqrt(sum(value * value for value in resized))
    if norm == 0:
        raise EmbeddingProviderError("Embedding vector norm must be greater than zero")
    return [value / norm for value in resized]
