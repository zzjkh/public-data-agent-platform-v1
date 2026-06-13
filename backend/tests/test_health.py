from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_returns_ok() -> None:
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
        response = client.get("/health", headers={"X-Request-ID": "test-request-id"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_name": "public-data-agent",
        "environment": "test",
    }
    assert response.headers["X-Request-ID"] == "test-request-id"


def test_cors_preflight_allows_configured_frontend_origin() -> None:
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
        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
