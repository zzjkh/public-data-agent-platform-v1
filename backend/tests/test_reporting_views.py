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
from app.semantic.reporting_metadata import REPORTING_VIEW_NAMES, REPORTING_VIEW_SEEDS


EXPECTED_VIEW_COLUMNS = {
    "vw_population_yearly": {
        "region_code",
        "region_level",
        "parent_region_name",
        "parent_region_code",
        "region_name",
        "stat_year",
        "indicator_name",
        "value_numeric",
        "unit",
        "source",
        "source_url",
        "data_version",
    },
    "vw_gdp_yearly": {
        "region_code",
        "region_level",
        "parent_region_name",
        "parent_region_code",
        "region_name",
        "stat_year",
        "indicator_name",
        "value_numeric",
        "unit",
        "source",
        "source_url",
        "data_version",
    },
    "vw_dataset_catalog": {
        "dataset_name",
        "category",
        "department",
        "open_type",
        "update_date",
        "download_count",
        "api_count",
        "source_platform",
        "source_url",
        "update_frequency",
        "status",
    },
    "vw_dataset_category_stats": {"category", "dataset_count", "api_count", "latest_update_date"},
    "vw_dataset_department_stats": {"department", "dataset_count", "api_count", "latest_update_date"},
}


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


def test_reporting_metadata_seed_definition_is_complete() -> None:
    assert len(REPORTING_VIEW_SEEDS) == 5
    assert set(REPORTING_VIEW_NAMES) == {
        "reporting.vw_population_yearly",
        "reporting.vw_gdp_yearly",
        "reporting.vw_dataset_catalog",
        "reporting.vw_dataset_category_stats",
        "reporting.vw_dataset_department_stats",
    }
    assert sum(len(view.fields) for view in REPORTING_VIEW_SEEDS) == 43


def test_reporting_views_exist_after_migration() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://app:app@localhost:55432/public_data_agent",
    )
    if not database_available(database_url):
        pytest.skip("PostgreSQL test database is not available.")

    upgrade_to_head(database_url)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    view_names = set(inspector.get_view_names(schema="reporting"))
    assert view_names.issuperset(EXPECTED_VIEW_COLUMNS)

    for view_name, expected_columns in EXPECTED_VIEW_COLUMNS.items():
        columns = {column["name"] for column in inspector.get_columns(view_name, schema="reporting")}
        assert columns == expected_columns

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM reporting_views")) == 5
        assert connection.scalar(text("SELECT COUNT(*) FROM reporting_view_fields")) == 43
        for view_name in EXPECTED_VIEW_COLUMNS:
            connection.execute(text(f"SELECT * FROM reporting.{view_name} LIMIT 1")).fetchall()


def upgrade_to_head(database_url: str) -> None:
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
