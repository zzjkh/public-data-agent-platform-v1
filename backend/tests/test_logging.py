from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_request_id_header_is_generated_when_missing() -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://app:app@localhost:55432/public_data_agent",
        readonly_database_url=(
            "postgresql+psycopg://app_readonly:app_readonly@localhost:55432/public_data_agent"
        ),
        deepseek_api_key="test-key",
        jwt_secret_key="test-secret-at-least-32-bytes-long",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
