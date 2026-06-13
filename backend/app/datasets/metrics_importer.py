from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.document import SourceFile
from app.db.repositories.dataset import MetricRepository
from app.db.repositories.source_file import SourceFileRepository
from app.datasets.importers import (
    DatasetImportError,
    clean_text,
    metadata_from_row,
    parse_int,
    read_tabular_rows,
)
from app.files.storage import LocalFileStorage


SUPPORTED_METRIC_FILE_TYPES = {"csv", "xlsx"}
VALID_DOMAINS = {"economy", "population", "open_data", "other"}
VALID_PERIODS = {"annual", "quarterly", "monthly"}
LONG_FORMAT_REQUIRED_COLUMNS = {"indicator_code", "indicator_name", "stat_year"}
LONG_FORMAT_COLUMNS = {
    "indicator_code",
    "indicator_name",
    "domain",
    "region_code",
    "region_name",
    "stat_period",
    "stat_year",
    "stat_month",
    "value_numeric",
    "value_text",
    "unit",
    "source",
    "source_url",
    "data_version",
    "aliases",
    "description",
}
WIDE_DIMENSION_COLUMNS = {
    "stat_year",
    "year",
    "年份",
    "region_code",
    "region_name",
    "地区",
    "stat_period",
    "source",
    "source_url",
    "data_version",
}
BUILT_IN_METRIC_MAPPINGS = {
    "gdp": {
        "indicator_code": "gdp_total",
        "indicator_name": "地区生产总值",
        "domain": "economy",
        "unit": "亿元",
        "aliases": ["GDP", "北京GDP"],
    },
    "地区生产总值": {
        "indicator_code": "gdp_total",
        "indicator_name": "地区生产总值",
        "domain": "economy",
        "unit": "亿元",
        "aliases": ["GDP", "北京GDP"],
    },
    "常住人口": {
        "indicator_code": "resident_population",
        "indicator_name": "常住人口",
        "domain": "population",
        "unit": "万人",
        "aliases": ["人口规模", "年末常住人口", "北京人口"],
    },
    "resident_population": {
        "indicator_code": "resident_population",
        "indicator_name": "常住人口",
        "domain": "population",
        "unit": "万人",
        "aliases": ["人口规模", "年末常住人口", "北京人口"],
    },
}


class MetricImportError(DatasetImportError):
    pass


@dataclass(frozen=True)
class MetricImportOptions:
    format: str = "auto"
    default_region_code: str | None = None
    default_region_name: str = "北京市"
    default_stat_period: str = "annual"
    default_data_version: str = "v1"
    default_source: str | None = None
    default_source_url: str | None = None
    metric_mappings: dict[str, dict[str, Any]] | None = None


@dataclass(frozen=True)
class MetricImportResult:
    source_file_id: UUID
    input_format: str
    source_rows: int
    metric_rows: int
    metrics_created: int
    metrics_updated: int
    values_created: int
    values_updated: int
    rows_skipped: int


@dataclass(frozen=True)
class MetricRow:
    indicator_code: str
    indicator_name: str
    domain: str
    region_code: str | None
    region_name: str
    stat_period: str
    stat_year: int | None
    stat_month: int | None
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    source: str | None
    source_url: str | None
    data_version: str
    aliases: list[str]
    description: str | None
    dimension_json: dict[str, Any]


class MetricImporter:
    def __init__(self, db: Session, storage: LocalFileStorage) -> None:
        self.db = db
        self.storage = storage
        self.source_files = SourceFileRepository(db)
        self.metrics = MetricRepository(db)

    def import_from_source_file(
        self,
        *,
        source_file_id: UUID,
        options: MetricImportOptions | None = None,
    ) -> MetricImportResult:
        options = options or MetricImportOptions()
        source_file = self._get_metric_source_file(source_file_id)
        try:
            source_rows = read_tabular_rows(
                self.storage.resolve(source_file.storage_uri),
                file_type=source_file.file_type,
            )
            result = self._import_rows(
                source_file=source_file,
                source_rows=source_rows,
                options=options,
            )
        except Exception as exc:
            source_file.parse_status = "failed"
            source_file.error_message = str(exc)
            self.db.flush()
            raise

        source_file.parse_status = "parsed"
        source_file.error_message = None
        self.db.flush()
        return result

    def _get_metric_source_file(self, source_file_id: UUID) -> SourceFile:
        source_file = self.source_files.get_by_id(source_file_id)
        if source_file is None:
            raise MetricImportError("Metric source file not found")
        if source_file.file_type not in SUPPORTED_METRIC_FILE_TYPES:
            raise MetricImportError(f"Metric source file must be csv or xlsx, got {source_file.file_type}")
        return source_file

    def _import_rows(
        self,
        *,
        source_file: SourceFile,
        source_rows: list[dict[str, Any]],
        options: MetricImportOptions,
    ) -> MetricImportResult:
        if not source_rows:
            raise MetricImportError("Metric source file is empty")
        input_format = detect_input_format(source_rows, configured_format=options.format)
        metric_rows = (
            long_rows_to_metric_rows(source_rows, options=options)
            if input_format == "long"
            else wide_rows_to_metric_rows(source_rows, options=options)
        )
        if not metric_rows:
            raise MetricImportError("Metric import produced no metric rows")

        metrics_created = 0
        metrics_updated = 0
        values_created = 0
        values_updated = 0
        rows_skipped = len(source_rows) - len(metric_rows) if input_format == "long" else 0
        metric_by_code = {}

        for row in metric_rows:
            metric = metric_by_code.get(row.indicator_code)
            if metric is None:
                metric, metric_created = self.metrics.upsert_metric(
                    {
                        "indicator_code": row.indicator_code,
                        "indicator_name": row.indicator_name,
                        "domain": row.domain,
                        "unit": row.unit,
                        "description": row.description,
                        "aliases_json": row.aliases,
                        "source_dataset_id": None,
                    }
                )
                metric_by_code[row.indicator_code] = metric
                if metric_created:
                    metrics_created += 1
                else:
                    metrics_updated += 1

            _, value_created = self.metrics.upsert_value(
                {
                    "metric_id": metric.id,
                    "indicator_code": row.indicator_code,
                    "indicator_name": row.indicator_name,
                    "region_code": row.region_code,
                    "region_name": row.region_name,
                    "stat_period": row.stat_period,
                    "stat_year": row.stat_year,
                    "stat_month": row.stat_month,
                    "value_numeric": row.value_numeric,
                    "value_text": row.value_text,
                    "unit": row.unit,
                    "dimension_json": row.dimension_json,
                    "source": row.source,
                    "source_url": row.source_url,
                    "data_version": row.data_version,
                }
            )
            if value_created:
                values_created += 1
            else:
                values_updated += 1

        return MetricImportResult(
            source_file_id=source_file.id,
            input_format=input_format,
            source_rows=len(source_rows),
            metric_rows=len(metric_rows),
            metrics_created=metrics_created,
            metrics_updated=metrics_updated,
            values_created=values_created,
            values_updated=values_updated,
            rows_skipped=rows_skipped,
        )


def detect_input_format(rows: list[dict[str, Any]], *, configured_format: str) -> str:
    if configured_format not in {"auto", "long", "wide"}:
        raise MetricImportError("format must be auto, long or wide")
    if configured_format != "auto":
        return configured_format
    columns = set(rows[0])
    if LONG_FORMAT_REQUIRED_COLUMNS.issubset(columns):
        return "long"
    if find_year_column(rows[0]) is not None:
        return "wide"
    raise MetricImportError("Cannot detect metric file format")


def long_rows_to_metric_rows(rows: list[dict[str, Any]], *, options: MetricImportOptions) -> list[MetricRow]:
    metric_rows: list[MetricRow] = []
    for row in rows:
        indicator_code = clean_text(row.get("indicator_code"))
        indicator_name = clean_text(row.get("indicator_name"))
        if not indicator_code or not indicator_name:
            continue
        metric_rows.append(
            MetricRow(
                indicator_code=indicator_code,
                indicator_name=indicator_name,
                domain=normalize_domain(row.get("domain")),
                region_code=clean_text(row.get("region_code")) or options.default_region_code,
                region_name=clean_text(row.get("region_name")) or options.default_region_name,
                stat_period=normalize_period(row.get("stat_period")) or options.default_stat_period,
                stat_year=parse_optional_int(row.get("stat_year")),
                stat_month=parse_optional_int(row.get("stat_month")),
                value_numeric=parse_optional_float(row.get("value_numeric")),
                value_text=clean_text(row.get("value_text")),
                unit=clean_text(row.get("unit")),
                source=clean_text(row.get("source")) or options.default_source,
                source_url=clean_text(row.get("source_url")) or options.default_source_url,
                data_version=clean_text(row.get("data_version")) or options.default_data_version,
                aliases=parse_aliases(row.get("aliases")),
                description=clean_text(row.get("description")),
                dimension_json=metadata_from_row(row, known_columns=LONG_FORMAT_COLUMNS),
            )
        )
    return metric_rows


def wide_rows_to_metric_rows(rows: list[dict[str, Any]], *, options: MetricImportOptions) -> list[MetricRow]:
    metric_rows: list[MetricRow] = []
    for row in rows:
        year_column = find_year_column(row)
        if year_column is None:
            continue
        stat_year = parse_optional_int(row.get(year_column))
        region_name = clean_text(row.get("region_name")) or clean_text(row.get("地区")) or options.default_region_name
        region_code = clean_text(row.get("region_code")) or options.default_region_code
        stat_period = normalize_period(row.get("stat_period")) or options.default_stat_period
        source = clean_text(row.get("source")) or options.default_source
        source_url = clean_text(row.get("source_url")) or options.default_source_url
        data_version = clean_text(row.get("data_version")) or options.default_data_version

        for column, value in row.items():
            if column in WIDE_DIMENSION_COLUMNS or value in (None, ""):
                continue
            mapping = resolve_metric_mapping(column, options.metric_mappings)
            value_numeric = parse_optional_float(value)
            value_text = None if value_numeric is not None else clean_text(value)
            metric_rows.append(
                MetricRow(
                    indicator_code=mapping["indicator_code"],
                    indicator_name=mapping["indicator_name"],
                    domain=normalize_domain(mapping.get("domain")),
                    region_code=region_code,
                    region_name=region_name,
                    stat_period=stat_period,
                    stat_year=stat_year,
                    stat_month=None,
                    value_numeric=value_numeric,
                    value_text=value_text,
                    unit=clean_text(mapping.get("unit")),
                    source=source,
                    source_url=source_url,
                    data_version=data_version,
                    aliases=parse_aliases(mapping.get("aliases")),
                    description=clean_text(mapping.get("description")),
                    dimension_json={},
                )
            )
    return metric_rows


def resolve_metric_mapping(column: str, mappings: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    mapping = (mappings or {}).get(column) or BUILT_IN_METRIC_MAPPINGS.get(column)
    normalized_column = column.lower()
    mapping = mapping or BUILT_IN_METRIC_MAPPINGS.get(normalized_column)
    if mapping is not None:
        return {
            "indicator_code": mapping["indicator_code"],
            "indicator_name": mapping["indicator_name"],
            "domain": mapping.get("domain", "other"),
            "unit": mapping.get("unit"),
            "aliases": mapping.get("aliases", []),
            "description": mapping.get("description"),
        }
    indicator_name = clean_text(column) or "未命名指标"
    return {
        "indicator_code": slugify_metric_code(indicator_name),
        "indicator_name": indicator_name,
        "domain": "other",
        "unit": None,
        "aliases": [],
        "description": None,
    }


def find_year_column(row: dict[str, Any]) -> str | None:
    for column in ("stat_year", "year", "年份"):
        if column in row:
            return column
    return None


def normalize_domain(value: Any) -> str:
    domain = clean_text(value) or "other"
    return domain if domain in VALID_DOMAINS else "other"


def normalize_period(value: Any) -> str | None:
    period = clean_text(value)
    if period is None:
        return None
    if period not in VALID_PERIODS:
        raise MetricImportError(f"Invalid stat_period: {period}")
    return period


def parse_optional_int(value: Any) -> int | None:
    if clean_text(value) is None:
        return None
    return parse_int(value)


def parse_optional_float(value: Any) -> float | None:
    text = clean_text(value)
    if text is None:
        return None
    normalized = text.replace(",", "").replace("，", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def parse_aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = clean_text(value)
    if text is None:
        return []
    return [part.strip() for part in re.split(r"[,，;；、|]", text) if part.strip()]


def slugify_metric_code(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    if normalized:
        return normalized
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"metric_{digest}"
