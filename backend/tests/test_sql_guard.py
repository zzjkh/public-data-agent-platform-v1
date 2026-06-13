from __future__ import annotations

from app.analytics.sql_guard import SQLGuard, validate_sql


def violation_codes(sql: str) -> set[str]:
    return {violation.code for violation in validate_sql(sql).violations}


def test_sql_guard_accepts_reporting_select_and_preserves_limit() -> None:
    result = validate_sql(
        "SELECT stat_year, value_numeric, unit "
        "FROM reporting.vw_gdp_yearly "
        "WHERE region_name = '北京市' "
        "ORDER BY stat_year ASC LIMIT 50"
    )

    assert result.valid
    assert not result.rewritten
    assert result.validated_sql is not None
    assert "reporting.vw_gdp_yearly" in result.validated_sql
    assert "LIMIT 50" in result.validated_sql


def test_sql_guard_accepts_where_conditions() -> None:
    result = validate_sql(
        "SELECT stat_year, value_numeric "
        "FROM reporting.vw_population_yearly "
        "WHERE region_name = '北京市' AND stat_year BETWEEN 2022 AND 2026 "
        "ORDER BY stat_year ASC LIMIT 100"
    )

    assert result.valid
    assert result.validated_sql is not None
    assert "BETWEEN 2022 AND 2026" in result.validated_sql


def test_sql_guard_accepts_cte_when_sources_are_reporting_views() -> None:
    result = validate_sql(
        "WITH yearly AS ("
        "SELECT stat_year, value_numeric FROM reporting.vw_gdp_yearly WHERE region_name = '北京市'"
        ") SELECT stat_year, value_numeric FROM yearly ORDER BY stat_year LIMIT 5"
    )

    assert result.valid
    assert result.validated_sql is not None
    assert "WITH yearly AS" in result.validated_sql


def test_sql_guard_adds_default_limit() -> None:
    result = validate_sql("SELECT stat_year FROM reporting.vw_gdp_yearly")

    assert result.valid
    assert result.rewritten
    assert result.validated_sql is not None
    assert "LIMIT 100" in result.validated_sql


def test_sql_guard_caps_large_limit() -> None:
    result = validate_sql("SELECT stat_year FROM reporting.vw_gdp_yearly LIMIT 1000")

    assert result.valid
    assert result.rewritten
    assert result.validated_sql is not None
    assert "LIMIT 200" in result.validated_sql


def test_sql_guard_allows_count_star_but_rejects_projection_star() -> None:
    count_result = validate_sql("SELECT count(*) FROM reporting.vw_gdp_yearly LIMIT 1")
    star_result = validate_sql("SELECT * FROM reporting.vw_gdp_yearly LIMIT 1")
    table_star_result = validate_sql("SELECT g.* FROM reporting.vw_gdp_yearly AS g LIMIT 1")

    assert count_result.valid
    assert "SELECT_STAR" in {violation.code for violation in star_result.violations}
    assert "SELECT_STAR" in {violation.code for violation in table_star_result.violations}


def test_sql_guard_rejects_non_select_and_multi_statement_sql() -> None:
    assert "NON_SELECT_STATEMENT" in violation_codes(
        "DELETE FROM reporting.vw_gdp_yearly WHERE stat_year = 2024"
    )
    assert "MULTI_STATEMENT" in violation_codes(
        "SELECT stat_year FROM reporting.vw_gdp_yearly LIMIT 1; "
        "SELECT stat_year FROM reporting.vw_population_yearly LIMIT 1"
    )
    assert "NON_SELECT_STATEMENT" in violation_codes(
        "SELECT stat_year FROM reporting.vw_gdp_yearly "
        "UNION SELECT stat_year FROM reporting.vw_population_yearly LIMIT 1"
    )


def test_sql_guard_rejects_select_into_even_though_it_is_select() -> None:
    assert "SELECT_INTO" in violation_codes(
        "SELECT stat_year INTO temp_table FROM reporting.vw_gdp_yearly LIMIT 1"
    )


def test_sql_guard_rejects_non_reporting_schema_and_unqualified_table() -> None:
    assert "NON_REPORTING_SCHEMA" in violation_codes("SELECT id FROM public.users LIMIT 1")
    assert "SCHEMA_REQUIRED" in violation_codes("SELECT stat_year FROM vw_gdp_yearly LIMIT 1")


def test_sql_guard_rejects_table_outside_reporting_whitelist() -> None:
    assert "TABLE_NOT_ALLOWED" in violation_codes(
        "SELECT stat_year FROM reporting.unknown_view LIMIT 1"
    )


def test_sql_guard_rejects_blocked_and_unknown_functions() -> None:
    assert "BLOCKED_FUNCTION" in violation_codes(
        "SELECT pg_sleep(1) FROM reporting.vw_gdp_yearly LIMIT 1"
    )
    assert "FUNCTION_NOT_ALLOWED" in violation_codes(
        "SELECT round(value_numeric, 2) FROM reporting.vw_gdp_yearly LIMIT 1"
    )


def test_sql_guard_rejects_expression_limit() -> None:
    assert "INVALID_LIMIT" in violation_codes(
        "SELECT stat_year FROM reporting.vw_gdp_yearly LIMIT 10 + 1"
    )


def test_sql_guard_uses_configurable_limits_and_tables() -> None:
    guard = SQLGuard(
        allowed_tables={"reporting.vw_custom"},
        default_limit=25,
        max_limit=30,
    )

    result = guard.validate("SELECT stat_year FROM reporting.vw_custom LIMIT 100")

    assert result.valid
    assert result.validated_sql is not None
    assert "LIMIT 30" in result.validated_sql
