from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def valid_settings_kwargs() -> dict[str, object]:
    return {
        "database_url": "postgresql+psycopg://app:app@localhost:55432/public_data_agent",
        "readonly_database_url": (
            "postgresql+psycopg://app_readonly:app_readonly@localhost:55432/public_data_agent"
        ),
        "deepseek_api_key": "test-key",
        "jwt_secret_key": "test-secret",
    }


def build_settings(**overrides: object) -> Settings:
    values = valid_settings_kwargs()
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_accept_valid_minimum_config() -> None:
    settings = build_settings()

    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.llm_thinking_mode == "disabled"
    assert settings.sql_max_rows == 200
    assert settings.ocr_engine == "rapidocr"
    assert settings.ocr_render_dpi == 180
    assert settings.embedding_provider == "sentence_transformers"
    assert settings.embedding_model == "Qwen/Qwen3-Embedding-4B"
    assert settings.embedding_dim == 1024
    assert settings.embedding_query_instruction
    assert settings.embedding_max_retries == 1
    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_settings_accepts_pro_model_override() -> None:
    settings = build_settings(deepseek_model="deepseek-v4-pro", llm_thinking_mode="enabled")

    assert settings.deepseek_model == "deepseek-v4-pro"
    assert settings.llm_thinking_mode == "enabled"


def test_settings_rejects_unknown_model() -> None:
    with pytest.raises(ValidationError, match="deepseek-v4-flash"):
        build_settings(deepseek_model="deepseek-v3")


def test_settings_rejects_unknown_thinking_mode() -> None:
    with pytest.raises(ValidationError, match="disabled"):
        build_settings(llm_thinking_mode="auto")


def test_settings_rejects_same_readonly_database_url() -> None:
    kwargs = valid_settings_kwargs()
    kwargs["readonly_database_url"] = kwargs["database_url"]

    with pytest.raises(ValidationError, match="READONLY_DATABASE_URL"):
        Settings(_env_file=None, **kwargs)


def test_settings_accepts_remote_embedding_provider() -> None:
    settings = build_settings(
        embedding_provider="remote_http",
        embedding_remote_url="http://embedding-server:8080/v1/embeddings",
        embedding_remote_api_format="openai",
    )

    assert settings.embedding_provider == "remote_http"
    assert settings.embedding_remote_url == "http://embedding-server:8080/v1/embeddings"


def test_settings_requires_remote_embedding_url() -> None:
    with pytest.raises(ValidationError, match="EMBEDDING_REMOTE_URL"):
        build_settings(embedding_provider="remote_http")


def test_settings_rejects_invalid_remote_embedding_url() -> None:
    with pytest.raises(ValidationError, match="http:// or https://"):
        build_settings(
            embedding_provider="remote_http",
            embedding_remote_url="embedding-server:8080/v1/embeddings",
        )


def test_settings_rejects_default_admin_credentials_in_production() -> None:
    with pytest.raises(ValidationError, match="Default admin seed credentials"):
        build_settings(app_env="production")


def test_settings_rejects_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        build_settings(cors_allowed_origins=["*"])
