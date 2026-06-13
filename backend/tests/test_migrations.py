from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def database_available(database_url: str) -> bool:
    url = make_url(database_url)
    try:
        with psycopg.connect(
            host=url.host,
            port=url.port or 5432,
            dbname=url.database,
            user=url.username,
            password=url.password,
            connect_timeout=2,
        ):
            return True
    except psycopg.Error:
        return False


def test_alembic_upgrade_head() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://app:app@localhost:55432/public_data_agent",
    )
    if not database_available(database_url):
        pytest.skip("PostgreSQL test database is not available.")

    project_root = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

    env = {
        "APP_ENV": "test",
        "DATABASE_URL": database_url,
        "READONLY_DATABASE_URL": (
            os.getenv(
                "READONLY_DATABASE_URL",
                "postgresql+psycopg://app_readonly:app_readonly@localhost:55432/public_data_agent",
            )
        ),
        "DEEPSEEK_API_KEY": "test-key",
        "JWT_SECRET_KEY": "test-secret-at-least-32-bytes-long",
    }
    old_env = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    get_settings.cache_clear()
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "users" in inspector.get_table_names()
    assert "source_files" in inspector.get_table_names()
    assert "ingestion_jobs" in inspector.get_table_names()
    assert "rag_chunks" in inspector.get_table_names()
    assert "chunk_embeddings" in inspector.get_table_names()
    assert "chunk_embeddings_512_legacy" in inspector.get_table_names()
    assert "open_datasets" in inspector.get_table_names()
    assert "open_dataset_fields" in inspector.get_table_names()
    assert "metrics" in inspector.get_table_names()
    assert "metric_values" in inspector.get_table_names()
    assert "reporting_views" in inspector.get_table_names()
    assert "reporting_view_fields" in inspector.get_table_names()
    assert "semantic_metadata_items" in inspector.get_table_names()
    assert "semantic_metadata_embeddings" in inspector.get_table_names()
    assert "semantic_metadata_embeddings_512_legacy" in inspector.get_table_names()
    assert "qa_traces" in inspector.get_table_names()
    assert "qa_trace_spans" in inspector.get_table_names()
    assert "eval_cases" in inspector.get_table_names()
    assert "eval_runs" in inspector.get_table_names()
    assert "eval_results" in inspector.get_table_names()
    assert "source_url" in {column["name"] for column in inspector.get_columns("metric_values")}
    assert "embedding_text" in {
        column["name"] for column in inspector.get_columns("semantic_metadata_items")
    }
    assert set(inspector.get_view_names(schema="reporting")).issuperset(
        {
            "vw_population_yearly",
            "vw_gdp_yearly",
            "vw_dataset_catalog",
            "vw_dataset_category_stats",
            "vw_dataset_department_stats",
        }
    )
    assert {"region_code", "region_level", "parent_region_name", "parent_region_code"}.issubset(
        {column["name"] for column in inspector.get_columns("vw_gdp_yearly", schema="reporting")}
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT extname FROM pg_extension WHERE extname='vector'"))
        assert connection.scalar(
            text("SELECT schema_name FROM information_schema.schemata WHERE schema_name='reporting'")
        )
