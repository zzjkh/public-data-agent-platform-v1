from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.api.deps import get_db
from app.auth.security import hash_password
from app.core.config import Settings
from app.db.base import Base
from app.db.models.user import User
from app.main import create_app


def make_test_settings(tmp_path: Path | None = None) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        readonly_database_url="sqlite+pysqlite:///:readonly:",
        deepseek_api_key="test-key",
        jwt_secret_key="test-secret-at-least-32-bytes-long",
        embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_version="v1",
        embedding_dim=512,
        embedding_provider="sentence_transformers",
        file_storage_root=str(tmp_path or Path("data/test-uploads")),
    )


def make_test_client(tmp_path: Path | None = None) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as db:
        db.add_all(
            [
                User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role="admin",
                    is_active=True,
                ),
                User(
                    username="demo",
                    password_hash=hash_password("demo123"),
                    role="user",
                    is_active=True,
                ),
            ]
        )
        db.commit()

    app = create_app(make_test_settings(tmp_path))

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def auth_headers(client: TestClient, *, username: str = "admin", password: str = "admin123") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
