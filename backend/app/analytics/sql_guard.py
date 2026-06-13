from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.semantic.reporting_metadata import REPORTING_VIEW_SEEDS


DEFAULT_ALLOWED_TABLES = frozenset(seed.full_name.lower() for seed in REPORTING_VIEW_SEEDS)
DEFAULT_ALLOWED_FUNCTIONS = frozenset({"count", "sum", "avg", "min", "max"})
DEFAULT_BLOCKED_FUNCTIONS = frozenset(
    {
        "copy",
        "dblink",
        "lo_export",
        "lo_import",
        "pg_read_file",
        "pg_sleep",
        "pg_write_file",
    }
)

BLOCKED_EXPRESSION_TYPES = tuple(
    getattr(exp, name)
    for name in (
        "Alter",
        "Command",
        "Copy",
        "Create",
        "Delete",
        "Drop",
        "Insert",
        "Update",
    )
    if hasattr(exp, name)
)


@dataclass(frozen=True)
class SQLViolation:
    code: str
    message: str


@dataclass(frozen=True)
class SQLGuardResult:
    valid: bool
    validated_sql: str | None
    violations: tuple[SQLViolation, ...]
    rewritten: bool


class SQLGuard:
    def __init__(
        self,
        *,
        allowed_schema: str = "reporting",
        allowed_tables: Iterable[str] = DEFAULT_ALLOWED_TABLES,
        allowed_functions: Iterable[str] = DEFAULT_ALLOWED_FUNCTIONS,
        blocked_functions: Iterable[str] = DEFAULT_BLOCKED_FUNCTIONS,
        default_limit: int = 100,
        max_limit: int = 200,
    ) -> None:
        if default_limit < 1:
            raise ValueError("default_limit must be positive")
        if max_limit < default_limit:
            raise ValueError("max_limit must be greater than or equal to default_limit")

        self.allowed_schema = allowed_schema.lower()
        self.allowed_tables = frozenset(table.lower() for table in allowed_tables)
        self.allowed_functions = frozenset(function.lower() for function in allowed_functions)
        self.blocked_functions = frozenset(function.lower() for function in blocked_functions)
        self.default_limit = default_limit
        self.max_limit = max_limit

    def validate(self, sql: str) -> SQLGuardResult:
        violations: list[SQLViolation] = []
        stripped_sql = sql.strip()
        if not stripped_sql:
            return SQLGuardResult(
                valid=False,
                validated_sql=None,
                violations=(SQLViolation("EMPTY_SQL", "SQL must not be empty"),),
                rewritten=False,
            )

        try:
            statements = [statement for statement in sqlglot.parse(stripped_sql, read="postgres") if statement]
        except ParseError as exc:
            return SQLGuardResult(
                valid=False,
                validated_sql=None,
                violations=(SQLViolation("PARSE_ERROR", str(exc)),),
                rewritten=False,
            )

        if len(statements) != 1:
            return SQLGuardResult(
                valid=False,
                validated_sql=None,
                violations=(
                    SQLViolation("MULTI_STATEMENT", "Only one SQL statement is allowed"),
                ),
                rewritten=False,
            )

        statement = statements[0]
        if not isinstance(statement, exp.Select):
            return SQLGuardResult(
                valid=False,
                validated_sql=None,
                violations=(
                    SQLViolation("NON_SELECT_STATEMENT", "Only SELECT statements are allowed"),
                ),
                rewritten=False,
            )

        self._validate_select_into(statement, violations)
        self._validate_blocked_expressions(statement, violations)
        self._validate_projection_wildcards(statement, violations)
        self._validate_tables(statement, violations)
        self._validate_functions(statement, violations)
        limit_value = self._validate_limit(statement, violations)

        if violations:
            return SQLGuardResult(
                valid=False,
                validated_sql=None,
                violations=tuple(violations),
                rewritten=False,
            )

        rewritten_statement = statement.copy()
        rewritten = False
        if limit_value is None:
            rewritten_statement.limit(self.default_limit, copy=False)
            rewritten = True
        elif limit_value > self.max_limit:
            rewritten_statement.limit(self.max_limit, copy=False)
            rewritten = True

        return SQLGuardResult(
            valid=True,
            validated_sql=rewritten_statement.sql(dialect="postgres"),
            violations=(),
            rewritten=rewritten,
        )

    def _validate_select_into(
        self,
        statement: exp.Select,
        violations: list[SQLViolation],
    ) -> None:
        if statement.args.get("into") is not None:
            violations.append(
                SQLViolation("SELECT_INTO", "SELECT INTO is not allowed")
            )

    def _validate_blocked_expressions(
        self,
        statement: exp.Expression,
        violations: list[SQLViolation],
    ) -> None:
        for blocked in statement.find_all(*BLOCKED_EXPRESSION_TYPES):
            violations.append(
                SQLViolation(
                    "BLOCKED_STATEMENT",
                    f"SQL expression is not allowed: {blocked.key.upper()}",
                )
            )

    def _validate_projection_wildcards(
        self,
        statement: exp.Expression,
        violations: list[SQLViolation],
    ) -> None:
        for select in statement.find_all(exp.Select):
            for projection in select.expressions:
                expression = projection.this if isinstance(projection, exp.Alias) else projection
                if isinstance(expression, exp.Star):
                    violations.append(
                        SQLViolation("SELECT_STAR", "SELECT * is not allowed")
                    )
                if isinstance(expression, exp.Column) and isinstance(expression.this, exp.Star):
                    violations.append(
                        SQLViolation("SELECT_STAR", "SELECT table.* is not allowed")
                    )

    def _validate_tables(
        self,
        statement: exp.Expression,
        violations: list[SQLViolation],
    ) -> None:
        cte_names = self._cte_names(statement)
        for table in statement.find_all(exp.Table):
            table_name = normalize_identifier(table.name)
            schema_name = normalize_identifier(table.db)
            if table_name in cte_names and not schema_name:
                continue
            if not schema_name:
                violations.append(
                    SQLViolation(
                        "SCHEMA_REQUIRED",
                        f"Table must use explicit reporting schema: {table_name}",
                    )
                )
                continue
            if schema_name != self.allowed_schema:
                violations.append(
                    SQLViolation(
                        "NON_REPORTING_SCHEMA",
                        f"Only {self.allowed_schema} schema is allowed: {schema_name}.{table_name}",
                    )
                )
                continue
            full_name = f"{schema_name}.{table_name}"
            if full_name not in self.allowed_tables:
                violations.append(
                    SQLViolation(
                        "TABLE_NOT_ALLOWED",
                        f"Table is not in the reporting whitelist: {full_name}",
                    )
                )

    def _validate_functions(
        self,
        statement: exp.Expression,
        violations: list[SQLViolation],
    ) -> None:
        for function in statement.find_all(exp.Func):
            if isinstance(function, exp.Connector | exp.Binary):
                continue
            function_name = normalize_function_name(function)
            if function_name in self.blocked_functions:
                violations.append(
                    SQLViolation(
                        "BLOCKED_FUNCTION",
                        f"Function is blocked: {function_name}",
                    )
                )
                continue
            if function_name not in self.allowed_functions:
                violations.append(
                    SQLViolation(
                        "FUNCTION_NOT_ALLOWED",
                        f"Function is not in the V1 whitelist: {function_name}",
                    )
                )

    def _validate_limit(
        self,
        statement: exp.Select,
        violations: list[SQLViolation],
    ) -> int | None:
        limit = statement.args.get("limit")
        if limit is None or limit.expression is None:
            return None

        expression = limit.expression
        if not isinstance(expression, exp.Literal) or expression.is_string:
            violations.append(
                SQLViolation("INVALID_LIMIT", "LIMIT must be a positive integer literal")
            )
            return None

        raw_value = str(expression.this)
        if not raw_value.isdigit():
            violations.append(
                SQLViolation("INVALID_LIMIT", "LIMIT must be a positive integer literal")
            )
            return None

        value = int(raw_value)
        if value < 1:
            violations.append(
                SQLViolation("INVALID_LIMIT", "LIMIT must be greater than zero")
            )
            return None
        return value

    def _cte_names(self, statement: exp.Expression) -> set[str]:
        return {
            normalize_identifier(cte.alias)
            for cte in statement.find_all(exp.CTE)
            if normalize_identifier(cte.alias)
        }


def validate_sql(sql: str, **kwargs) -> SQLGuardResult:
    return SQLGuard(**kwargs).validate(sql)


def normalize_identifier(value: object) -> str:
    return str(value or "").strip().strip('"').lower()


def normalize_function_name(function: exp.Func) -> str:
    if isinstance(function, exp.Anonymous):
        return normalize_identifier(function.name)
    if function.key:
        return normalize_identifier(function.key)
    return normalize_identifier(function.sql_name())
