from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql as psycopg_sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

import app.analytics.sql_executor as sql_executor_module
from app.analytics.sql_executor import (
    SQLExecutionError,
    SQLExecutor,
    normalize_sql_value,
    quote_identifier,
)
from app.analytics.sql_guard import SQLGuard, SQLGuardResult
from app.core.config import Settings, get_settings


def make_executor_settings(
    *,
    database_url: str = "sqlite+pysqlite:///:main:",
    readonly_database_url: str = "sqlite+pysqlite:///:readonly:",
) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        readonly_database_url=readonly_database_url,
        deepseek_api_key="test-key",
        jwt_secret_key="test-secret-at-least-32-bytes-long",
    )


def test_sql_executor_creates_engine_from_readonly_database_url(monkeypatch) -> None:
    captured: dict[str, object] = {}
    real_create_engine = create_engine

    def fake_create_engine(url: str, *, pool_pre_ping: bool):
        captured["url"] = url
        captured["pool_pre_ping"] = pool_pre_ping
        return real_create_engine("sqlite+pysqlite:///:memory:")

    monkeypatch.setattr(sql_executor_module, "create_engine", fake_create_engine)

    SQLExecutor(settings=make_executor_settings(readonly_database_url="sqlite+pysqlite:///:ro:"))

    assert captured == {
        "url": "sqlite+pysqlite:///:ro:",
        "pool_pre_ping": True,
    }


def test_sql_executor_requires_valid_guard_result() -> None:
    executor = SQLExecutor(settings=make_executor_settings(), engine=create_engine("sqlite+pysqlite:///:memory:"))

    with pytest.raises(SQLExecutionError, match="valid SQLGuardResult"):
        executor.execute(SQLGuardResult(valid=False, validated_sql=None, violations=(), rewritten=False))


def test_sql_executor_returns_columns_rows_count_and_preview() -> None:
    executor = SQLExecutor(
        settings=make_executor_settings(),
        engine=create_engine("sqlite+pysqlite:///:memory:"),
        preview_rows=1,
    )
    guard_result = SQLGuardResult(
        valid=True,
        validated_sql="SELECT 1 AS value, '北京市' AS region UNION ALL SELECT 2, '上海市'",
        violations=(),
        rewritten=False,
    )

    result = executor.execute(guard_result)

    assert result.columns == ("value", "region")
    assert result.rows == (
        {"value": 1, "region": "北京市"},
        {"value": 2, "region": "上海市"},
    )
    assert result.row_count == 2
    assert result.result_preview == ({"value": 1, "region": "北京市"},)
    assert result.latency_ms >= 0


def test_sql_executor_normalizes_common_sql_values() -> None:
    assert normalize_sql_value(Decimal("10")) == 10
    assert normalize_sql_value(Decimal("10.25")) == 10.25
    assert normalize_sql_value(date(2026, 6, 5)) == "2026-06-05"


def test_quote_identifier_rejects_invalid_search_path_identifier() -> None:
    with pytest.raises(SQLExecutionError, match="Invalid SQL identifier"):
        quote_identifier("reporting; DROP SCHEMA public")


def test_sql_executor_executes_guarded_reporting_query_on_postgres() -> None:
    database_url, readonly_database_url = prepare_postgres_for_executor_test()
    settings = make_executor_settings(
        database_url=database_url,
        readonly_database_url=readonly_database_url,
    )
    guard_result = SQLGuard().validate(
        "SELECT count(*) AS dataset_count FROM reporting.vw_dataset_catalog LIMIT 1"
    )

    assert guard_result.valid
    result = SQLExecutor(settings=settings).execute(guard_result)

    assert result.columns == ("dataset_count",)
    assert result.row_count == 1
    assert result.result_preview == result.rows
    assert result.rows[0]["dataset_count"] >= 0


def test_sql_executor_sets_postgres_runtime_guards() -> None:
    database_url, readonly_database_url = prepare_postgres_for_executor_test()
    settings = make_executor_settings(
        database_url=database_url,
        readonly_database_url=readonly_database_url,
    )
    guard_result = SQLGuardResult(
        valid=True,
        validated_sql=(
            "SELECT current_setting('search_path') AS search_path, "
            "current_setting('statement_timeout') AS statement_timeout, "
            "current_setting('transaction_read_only') AS transaction_read_only"
        ),
        violations=(),
        rewritten=False,
    )

    result = SQLExecutor(settings=settings).execute(guard_result)

    assert result.rows == (
        {
            "search_path": "reporting",
            "statement_timeout": "5s",
            "transaction_read_only": "on",
        },
    )


def prepare_postgres_for_executor_test() -> tuple[str, str]:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://app:app@localhost:55432/public_data_agent",
    )
    readonly_database_url = os.getenv(
        "READONLY_DATABASE_URL",
        "postgresql+psycopg://app_readonly:app_readonly@localhost:55432/public_data_agent",
    )
    if not database_available(database_url):
        pytest.skip("PostgreSQL test database is not available.")

    ensure_readonly_role_exists(database_url, readonly_database_url)
    upgrade_to_head(database_url, readonly_database_url)
    grant_readonly_reporting_access(database_url, readonly_database_url)
    return database_url, readonly_database_url


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


def ensure_readonly_role_exists(database_url: str, readonly_database_url: str) -> None:
    role_name, password = readonly_role_credentials(readonly_database_url)
    url = make_url(database_url)
    with psycopg.connect(
        host=url.host,
        port=url.port or 5432,
        dbname=url.database,
        user=url.username,
        password=url.password,
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
            if cursor.fetchone() is None:
                cursor.execute(
                    psycopg_sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg_sql.Identifier(role_name),
                        psycopg_sql.Literal(password),
                    ),
                )


def grant_readonly_reporting_access(database_url: str, readonly_database_url: str) -> None:
    role_name, _ = readonly_role_credentials(readonly_database_url)
    url = make_url(database_url)
    with psycopg.connect(
        host=url.host,
        port=url.port or 5432,
        dbname=url.database,
        user=url.username,
        password=url.password,
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            role = psycopg_sql.Identifier(role_name)
            cursor.execute(psycopg_sql.SQL("GRANT USAGE ON SCHEMA reporting TO {}").format(role))
            cursor.execute(
                psycopg_sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO {}").format(
                    role
                )
            )
            cursor.execute(psycopg_sql.SQL("ALTER ROLE {} SET search_path = reporting").format(role))


def readonly_role_credentials(readonly_database_url: str) -> tuple[str, str]:
    url = make_url(readonly_database_url)
    role_name = url.username or "app_readonly"
    password = url.password or "app_readonly"
    return role_name, password


def upgrade_to_head(database_url: str, readonly_database_url: str) -> None:
    project_root = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))

    env = {
        "APP_ENV": "test",
        "DATABASE_URL": database_url,
        "READONLY_DATABASE_URL": readonly_database_url,
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
