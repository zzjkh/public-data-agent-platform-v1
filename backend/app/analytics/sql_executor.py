from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Result

from app.analytics.sql_guard import SQLGuardResult
from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class SQLExecutionResult:
    executed_sql: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int
    result_preview: tuple[dict[str, Any], ...]
    latency_ms: int


class SQLExecutionError(ValueError):
    pass


class SQLExecutor:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        engine: Engine | None = None,
        timeout_seconds: int | None = None,
        search_path: str | None = None,
        preview_rows: int = 20,
    ) -> None:
        if preview_rows < 1:
            raise ValueError("preview_rows must be positive")

        self.settings = settings or get_settings()
        self.engine = engine or create_readonly_engine(self.settings)
        self.timeout_seconds = timeout_seconds or self.settings.sql_timeout_seconds
        self.search_path = search_path or self.settings.sql_readonly_search_path
        self.preview_rows = preview_rows

    def execute(self, guard_result: SQLGuardResult) -> SQLExecutionResult:
        if not guard_result.valid or not guard_result.validated_sql:
            raise SQLExecutionError("SQLExecutor only executes a valid SQLGuardResult")

        sql = guard_result.validated_sql
        started_at = perf_counter()
        with self.engine.connect() as connection:
            with connection.begin():
                if connection.dialect.name == "postgresql":
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(
                        text(f"SET LOCAL statement_timeout = '{int(self.timeout_seconds)}s'")
                    )
                    connection.execute(
                        text(f"SET LOCAL search_path TO {quote_identifier(self.search_path)}")
                    )

                result = connection.execute(text(sql))
                rows = fetch_rows(result)

        latency_ms = int((perf_counter() - started_at) * 1000)
        return SQLExecutionResult(
            executed_sql=sql,
            columns=tuple(rows[0].keys()) if rows else tuple(result.keys()),
            rows=tuple(rows),
            row_count=len(rows),
            result_preview=tuple(rows[: self.preview_rows]),
            latency_ms=latency_ms,
        )


def create_readonly_engine(settings: Settings | None = None) -> Engine:
    current_settings = settings or get_settings()
    return create_engine(current_settings.readonly_database_url, pool_pre_ping=True)


def fetch_rows(result: Result[Any]) -> list[dict[str, Any]]:
    if not result.returns_rows:
        raise SQLExecutionError("SQL did not return rows")
    return [normalize_row(row._mapping) for row in result.fetchall()]


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: normalize_sql_value(value) for key, value in row.items()}


def normalize_sql_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def quote_identifier(identifier: str) -> str:
    normalized = identifier.strip()
    if not normalized.replace("_", "").isalnum() or not normalized:
        raise SQLExecutionError(f"Invalid SQL identifier: {identifier}")
    return f'"{normalized}"'
