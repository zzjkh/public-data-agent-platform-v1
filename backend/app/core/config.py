from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


AppEnv = Literal["development", "test", "production"]
LogFormat = Literal["json", "console"]
PdfExtractorMode = Literal["layout"]
OcrEngineName = Literal["rapidocr", "tesseract"]
EmbeddingProviderName = Literal["sentence_transformers", "remote_http"]
RemoteEmbeddingApiFormat = Literal["openai", "tei"]
DeepSeekModelName = Literal["deepseek-v4-flash", "deepseek-v4-pro"]
LLMThinkingMode = Literal["enabled", "disabled"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = "development"
    app_name: str = "public-data-agent"
    log_level: str = "INFO"
    log_format: LogFormat = "json"

    database_url: str
    readonly_database_url: str

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str
    deepseek_model: DeepSeekModelName = "deepseek-v4-flash"
    llm_thinking_mode: LLMThinkingMode = "disabled"
    llm_request_timeout_seconds: int = Field(default=30, ge=1)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    llm_rate_limit_qps: int = Field(default=2, ge=1)
    llm_rate_limit_burst: int = Field(default=5, ge=1)
    llm_max_tokens: int = Field(default=2048, ge=256)

    embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    embedding_version: str = "qwen3-embedding-4b-mrl1024-query-instruct-v1"
    embedding_dim: int = Field(default=1024, ge=1)
    embedding_query_instruction: str = (
        "Given a Chinese government data question, retrieve relevant policy passages, "
        "statistical tables, metrics, fields, and SQL metadata that answer the query."
    )
    embedding_batch_size: int = Field(default=8, ge=1)
    embedding_provider: EmbeddingProviderName = "sentence_transformers"
    embedding_max_retries: int = Field(default=1, ge=0, le=3)
    embedding_normalize: bool = True
    embedding_device: str | None = None
    embedding_remote_url: str | None = None
    embedding_remote_api_key: str | None = None
    embedding_remote_api_format: RemoteEmbeddingApiFormat = "openai"
    embedding_remote_trust_env: bool = False
    embedding_request_timeout_seconds: int = Field(default=30, ge=1)

    file_storage_root: str = "data/uploads"

    jwt_secret_key: str
    jwt_expire_minutes: int = Field(default=1440, ge=1)
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    sql_max_rows: int = Field(default=200, ge=1, le=200)
    sql_default_limit: int = Field(default=100, ge=1, le=200)
    sql_timeout_seconds: int = Field(default=5, ge=1)
    sql_allowed_schema: str = "reporting"
    sql_readonly_search_path: str = "reporting"

    worker_id: str = "local-worker-1"
    job_poll_interval_seconds: int = Field(default=2, ge=1)
    job_heartbeat_interval_seconds: int = Field(default=10, ge=1)
    job_heartbeat_timeout_seconds: int = Field(default=120, ge=1)
    job_max_retries: int = Field(default=2, ge=0)

    ocr_enabled: bool = True
    ocr_lang: str = "ch"
    ocr_engine: OcrEngineName = "rapidocr"
    ocr_render_dpi: int = Field(default=180, ge=72, le=400)
    ocr_min_text_length: int = Field(default=20, ge=1)
    ocr_agent_refine_enabled: bool = False
    pdf_extractor_mode: PdfExtractorMode = "layout"
    pdf_agent_refine_enabled: bool = False
    pdf_table_extraction_enabled: bool = True

    dev_seed_admin_username: str = "admin"
    dev_seed_admin_password: str = "admin123"
    dev_seed_demo_username: str = "demo"
    dev_seed_demo_password: str = "demo123"

    @model_validator(mode="after")
    def validate_project_rules(self) -> "Settings":
        if self.readonly_database_url == self.database_url:
            raise ValueError("READONLY_DATABASE_URL must not equal DATABASE_URL.")

        if self.sql_default_limit > self.sql_max_rows:
            raise ValueError("SQL_DEFAULT_LIMIT must be less than or equal to SQL_MAX_ROWS.")

        if not self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin.")
        if "*" in self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must not contain wildcard origins.")
        if any(not origin.startswith(("http://", "https://")) for origin in self.cors_allowed_origins):
            raise ValueError("CORS_ALLOWED_ORIGINS entries must start with http:// or https://.")

        if self.embedding_provider == "remote_http" and not self.embedding_remote_url:
            raise ValueError("EMBEDDING_REMOTE_URL is required when EMBEDDING_PROVIDER=remote_http.")
        if self.embedding_remote_url and not self.embedding_remote_url.startswith(("http://", "https://")):
            raise ValueError("EMBEDDING_REMOTE_URL must start with http:// or https://.")

        if self.app_env == "production":
            if self.jwt_secret_key == "replace_with_random_secret":
                raise ValueError("JWT_SECRET_KEY must be changed in production.")
            if (
                self.dev_seed_admin_username == "admin"
                and self.dev_seed_admin_password == "admin123"
            ):
                raise ValueError("Default admin seed credentials are forbidden in production.")

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
