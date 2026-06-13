from __future__ import annotations

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


@dataclass(frozen=True)
class ServerSettings:
    model_name: str = "Qwen/Qwen3-Embedding-4B"
    model_path: str = "Qwen/Qwen3-Embedding-4B"
    embedding_dim: int = 1024
    device: str = "cuda:0"
    model_dtype: str = "bfloat16"
    normalize_embeddings: bool = True
    api_key: str | None = None
    max_batch_size: int = 64
    max_text_chars: int = 8_000
    max_sequence_length: int = 2048
    encode_batch_size: int = 8
    host: str = "127.0.0.1"
    port: int = 18_080

    @classmethod
    def from_env(cls) -> ServerSettings:
        settings = cls(
            model_name=os.getenv("EMBEDDING_MODEL", cls.model_name),
            model_path=os.getenv("EMBEDDING_MODEL_PATH", cls.model_path),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", str(cls.embedding_dim))),
            device=os.getenv("EMBEDDING_DEVICE", cls.device),
            model_dtype=os.getenv("EMBEDDING_MODEL_DTYPE", cls.model_dtype),
            normalize_embeddings=env_bool("EMBEDDING_NORMALIZE", True),
            api_key=os.getenv("EMBEDDING_SERVER_API_KEY") or None,
            max_batch_size=int(
                os.getenv("EMBEDDING_SERVER_MAX_BATCH_SIZE", str(cls.max_batch_size))
            ),
            max_text_chars=int(
                os.getenv("EMBEDDING_SERVER_MAX_TEXT_CHARS", str(cls.max_text_chars))
            ),
            max_sequence_length=int(
                os.getenv("EMBEDDING_SERVER_MAX_SEQUENCE_LENGTH", str(cls.max_sequence_length))
            ),
            encode_batch_size=int(
                os.getenv("EMBEDDING_SERVER_ENCODE_BATCH_SIZE", str(cls.encode_batch_size))
            ),
            host=os.getenv("EMBEDDING_SERVER_HOST", cls.host),
            port=int(os.getenv("EMBEDDING_SERVER_PORT", str(cls.port))),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        positive_values = {
            "EMBEDDING_DIM": self.embedding_dim,
            "EMBEDDING_SERVER_MAX_BATCH_SIZE": self.max_batch_size,
            "EMBEDDING_SERVER_MAX_TEXT_CHARS": self.max_text_chars,
            "EMBEDDING_SERVER_MAX_SEQUENCE_LENGTH": self.max_sequence_length,
            "EMBEDDING_SERVER_ENCODE_BATCH_SIZE": self.encode_batch_size,
            "EMBEDDING_SERVER_PORT": self.port,
        }
        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.model_dtype not in {"float32", "float16", "bfloat16"}:
            raise ValueError("EMBEDDING_MODEL_DTYPE must be float32, float16 or bfloat16")
