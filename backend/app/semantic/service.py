from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.dataset import Metric, OpenDataset
from app.db.models.ingestion_job import IngestionJob
from app.db.models.reporting import ReportingView, ReportingViewField
from app.db.models.semantic_metadata import SEMANTIC_METADATA_TYPES, SemanticMetadataItem
from app.db.repositories.ingestion_job import IngestionJobRepository
from app.db.repositories.semantic_metadata import SemanticMetadataRepository
from app.ingestion.embeddings import embed_with_retries, validate_embedding_options
from app.llm.embedding_provider import EmbeddingProvider
from app.semantic.schemas import SemanticMetadataRebuildRequest


METRIC_VIEW_BY_CODE = {
    "resident_population": "reporting.vw_population_yearly",
    "gdp_total": "reporting.vw_gdp_yearly",
}

DEFAULT_METADATA_TYPES = list(SEMANTIC_METADATA_TYPES)


class SemanticMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class SemanticMetadataRebuildResult:
    metadata_types: list[str]
    item_count: int
    items_created: int
    items_updated: int
    embeddings_created: int
    embeddings_reused: int
    embeddings_deleted: int
    embedding_model: str
    embedding_dim: int
    embedding_version: str


@dataclass(frozen=True)
class StaticSemanticSeed:
    metadata_type: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    business_meaning: str | None = None
    related_table: str = ""
    related_field: str = ""
    unit: str | None = None
    time_grain: str | None = None
    ddl_snippet: str | None = None
    sql_example: str | None = None
    join_path: str | None = None
    metadata_json: dict[str, Any] | None = None


SQL_EXAMPLE_SEEDS = (
    StaticSemanticSeed(
        metadata_type="sql_example",
        name="年度常住人口趋势查询",
        description="查询北京市年度常住人口趋势，适合回答近五年人口规模变化。",
        aliases=("人口趋势", "人口规模变化", "常住人口近五年"),
        related_table="reporting.vw_population_yearly",
        time_grain="annual",
        sql_example=(
            "SELECT stat_year, value_numeric, unit "
            "FROM reporting.vw_population_yearly "
            "WHERE region_name = '北京市' "
            "ORDER BY stat_year ASC "
            "LIMIT 100"
        ),
    ),
    StaticSemanticSeed(
        metadata_type="sql_example",
        name="年度地区生产总值趋势查询",
        description="查询北京市年度 GDP 趋势，适合回答地区生产总值变化。",
        aliases=("GDP趋势", "地区生产总值变化", "经济总量"),
        related_table="reporting.vw_gdp_yearly",
        time_grain="annual",
        sql_example=(
            "SELECT stat_year, value_numeric, unit "
            "FROM reporting.vw_gdp_yearly "
            "WHERE region_name = '北京市' "
            "ORDER BY stat_year ASC "
            "LIMIT 100"
        ),
    ),
    StaticSemanticSeed(
        metadata_type="sql_example",
        name="省内各市地区生产总值对比",
        description="按上级行政区和城市层级筛选某省下辖城市，并按 GDP 从高到低比较。",
        aliases=("浙江各市经济对比", "省内城市GDP排名", "下辖市生产总值"),
        related_table="reporting.vw_gdp_yearly",
        time_grain="annual",
        sql_example=(
            "SELECT region_name, stat_year, value_numeric, unit, source, data_version "
            "FROM reporting.vw_gdp_yearly "
            "WHERE parent_region_name = '浙江省' "
            "AND region_level = 'city' "
            "AND stat_year = 2023 "
            "ORDER BY value_numeric DESC "
            "LIMIT 100"
        ),
    ),
    StaticSemanticSeed(
        metadata_type="sql_example",
        name="开放数据分类统计查询",
        description="按主题分类统计开放数据集数量和接口数量。",
        aliases=("数据目录分类", "开放数据分类统计", "主题分类数据集数量"),
        related_table="reporting.vw_dataset_category_stats",
        sql_example=(
            "SELECT category, dataset_count, api_count, latest_update_date "
            "FROM reporting.vw_dataset_category_stats "
            "ORDER BY dataset_count DESC "
            "LIMIT 100"
        ),
    ),
    StaticSemanticSeed(
        metadata_type="sql_example",
        name="开放数据部门统计查询",
        description="按提供部门统计开放数据集数量和接口数量。",
        aliases=("部门开放数据", "数据提供部门统计", "部门数据集数量"),
        related_table="reporting.vw_dataset_department_stats",
        sql_example=(
            "SELECT department, dataset_count, api_count, latest_update_date "
            "FROM reporting.vw_dataset_department_stats "
            "ORDER BY dataset_count DESC "
            "LIMIT 100"
        ),
    ),
)

BUSINESS_RULE_SEEDS = (
    StaticSemanticSeed(
        metadata_type="business_rule",
        name="Text-to-SQL 只允许访问 reporting schema",
        description="LLM 生成 SQL 时只能访问 reporting.* 视图，不能访问业务底表。",
        aliases=("SQL安全边界", "只读视图", "reporting schema"),
        business_meaning="通过 reporting 视图限制可查询范围，降低越权和误查风险。",
        related_table="reporting",
    ),
    StaticSemanticSeed(
        metadata_type="business_rule",
        name="趋势查询按年份升序",
        description="涉及年度趋势时，SQL 应使用 stat_year 升序排序，方便回答变化过程。",
        aliases=("近五年", "年度趋势", "时间序列"),
        business_meaning="年度趋势默认 ORDER BY stat_year ASC。",
        related_table="reporting",
        related_field="stat_year",
        time_grain="annual",
    ),
    StaticSemanticSeed(
        metadata_type="business_rule",
        name="指标解释必须保留单位",
        description="解释 value_numeric 时必须同时读取 unit，避免亿元、万人等单位混淆。",
        aliases=("单位一致性", "数值单位", "指标口径"),
        business_meaning="回答结构化指标时，value_numeric 和 unit 需要一起使用。",
        related_table="reporting",
        related_field="unit",
    ),
    StaticSemanticSeed(
        metadata_type="business_rule",
        name="行政区比较使用父级关系",
        description="省内城市或市内区县比较必须按 parent_region_name 和 region_level 过滤。",
        aliases=("下辖城市", "省内各市", "行政区父级"),
        business_meaning="禁止依赖模型枚举行政区或使用名称后缀匹配代替父子关系。",
        related_table="reporting",
        related_field="parent_region_name,region_level",
    ),
    StaticSemanticSeed(
        metadata_type="business_rule",
        name="空结果需要触发 SQL repair",
        description="如果 SQL 执行结果为空，后续 QA 链路应允许最多一次修复重试。",
        aliases=("空结果", "SQL修复", "查询无结果"),
        business_meaning="降低因为时间范围、字段过滤过窄导致的错误回答。",
        related_table="reporting",
    ),
)


class SemanticMetadataService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repository = SemanticMetadataRepository(db)
        self.jobs = IngestionJobRepository(db)

    def create_rebuild_job(
        self,
        *,
        request: SemanticMetadataRebuildRequest,
        created_by: UUID | None,
    ) -> IngestionJob:
        metadata_types = normalize_metadata_types(request.types)
        job = self.jobs.create(
            job_type="rebuild_semantic_metadata",
            target_type="semantic_metadata",
            target_id=None,
            payload_json={
                "metadata_types": metadata_types,
                "force_rebuild": request.force_rebuild,
            },
            priority=request.priority,
            max_retries=(
                request.max_retries if request.max_retries is not None else self.settings.job_max_retries
            ),
            created_by=created_by,
        )
        self.db.commit()
        self.db.refresh(job)
        return job

    def list_items(
        self,
        *,
        page: int,
        page_size: int,
        metadata_type: str | None,
        keyword: str | None,
    ) -> tuple[list[SemanticMetadataItem], int]:
        if metadata_type is not None:
            normalize_metadata_types([metadata_type])
        return self.repository.list_items(
            page=page,
            page_size=page_size,
            metadata_type=metadata_type,
            keyword=keyword,
        )

    def rebuild_metadata(
        self,
        *,
        metadata_types: list[str] | None,
        provider: EmbeddingProvider,
        embedding_model: str,
        embedding_dim: int,
        embedding_version: str,
        batch_size: int,
        max_retries: int,
        force_rebuild: bool = False,
    ) -> SemanticMetadataRebuildResult:
        validate_embedding_options(batch_size=batch_size, max_retries=max_retries)
        selected_types = normalize_metadata_types(metadata_types)
        if provider.embedding_dim != embedding_dim:
            raise SemanticMetadataError(
                f"Provider dim mismatch: settings={embedding_dim}, provider={provider.embedding_dim}"
            )

        values = self.build_metadata_values(metadata_types=selected_types)
        created_count = 0
        updated_count = 0
        changed_item_ids: list[UUID] = []
        for value in values:
            item, created, changed = self.repository.upsert_item(value)
            if created:
                created_count += 1
            elif changed:
                updated_count += 1
            if changed:
                changed_item_ids.append(item.id)

        items = self.repository.list_items_for_embedding(metadata_types=selected_types)
        item_ids = [item.id for item in items]
        deleted_count = 0
        if force_rebuild:
            deleted_count += self.repository.delete_embeddings(
                item_ids=item_ids,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
            )
        else:
            deleted_count += self.repository.delete_embeddings(
                item_ids=changed_item_ids,
                embedding_model=embedding_model,
                embedding_version=embedding_version,
            )

        existing_item_ids = self.repository.get_existing_embedding_item_ids(
            item_ids=item_ids,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )
        pending_items = [item for item in items if item.id not in existing_item_ids]
        created_embeddings = []
        for batch in batched(pending_items, batch_size):
            vectors = embed_with_retries(
                provider=provider,
                texts=[item.embedding_text for item in batch],
                max_retries=max_retries,
            )
            rows = [
                semantic_embedding_row(
                    item=item,
                    vector=vector,
                    embedding_model=embedding_model,
                    embedding_dim=embedding_dim,
                    embedding_version=embedding_version,
                )
                for item, vector in zip(batch, vectors, strict=True)
            ]
            created_embeddings.extend(self.repository.create_embeddings(rows=rows))

        self.db.flush()
        return SemanticMetadataRebuildResult(
            metadata_types=selected_types,
            item_count=len(items),
            items_created=created_count,
            items_updated=updated_count,
            embeddings_created=len(created_embeddings),
            embeddings_reused=len(existing_item_ids),
            embeddings_deleted=deleted_count,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            embedding_version=embedding_version,
        )

    def build_metadata_values(self, *, metadata_types: list[str]) -> list[dict]:
        values: list[dict] = []
        if "dataset" in metadata_types:
            values.extend(self._dataset_items())
        if "table" in metadata_types:
            values.extend(self._table_items())
        if "field" in metadata_types:
            values.extend(self._field_items())
        if "metric" in metadata_types:
            values.extend(self._metric_items())
        if "sql_example" in metadata_types:
            values.extend(static_seed_to_values(SQL_EXAMPLE_SEEDS))
        if "business_rule" in metadata_types:
            values.extend(static_seed_to_values(BUSINESS_RULE_SEEDS))
        return values

    def _dataset_items(self) -> list[dict]:
        datasets = list(
            self.db.scalars(
                select(OpenDataset)
                .where(OpenDataset.status == "active")
                .order_by(OpenDataset.category.asc(), OpenDataset.name.asc())
            )
        )
        values = []
        for dataset in datasets:
            related_table = "reporting.vw_dataset_catalog"
            aliases = unique_strings([dataset.name, dataset.category, dataset.department])
            text = compact_lines(
                [
                    "类型：数据集",
                    f"名称：{dataset.name}",
                    f"分类：{dataset.category or ''}",
                    f"部门：{dataset.department or ''}",
                    f"开放类型：{dataset.open_type or ''}",
                    f"说明：{dataset.description or ''}",
                    f"可查询视图：{related_table}",
                ]
            )
            values.append(
                {
                    "metadata_type": "dataset",
                    "name": dataset.name,
                    "description": dataset.description,
                    "aliases_json": aliases,
                    "business_meaning": dataset.description,
                    "related_table": related_table,
                    "related_field": "dataset_name",
                    "embedding_text": text,
                    "search_text": text,
                    "metadata_json": {
                        "dataset_id": str(dataset.id),
                        "category": dataset.category,
                        "department": dataset.department,
                        "source_url": dataset.source_url,
                    },
                }
            )
        return values

    def _table_items(self) -> list[dict]:
        views = self._reporting_views_with_fields()
        values = []
        for view, fields in views:
            full_name = f"{view.schema_name}.{view.view_name}"
            field_names = [field.field_name for field in fields]
            ddl_snippet = f"CREATE VIEW {full_name} ({', '.join(field_names)});"
            text = compact_lines(
                [
                    "类型：可查询视图",
                    f"名称：{full_name}",
                    f"说明：{view.description or ''}",
                    f"字段：{', '.join(field_names)}",
                    f"DDL：{ddl_snippet}",
                ]
            )
            values.append(
                {
                    "metadata_type": "table",
                    "name": full_name,
                    "description": view.description,
                    "aliases_json": [view.view_name, full_name],
                    "business_meaning": view.description,
                    "related_table": full_name,
                    "related_field": "",
                    "ddl_snippet": ddl_snippet,
                    "embedding_text": text,
                    "search_text": text,
                    "metadata_json": {"field_names": field_names},
                }
            )
        return values

    def _field_items(self) -> list[dict]:
        values = []
        for view, fields in self._reporting_views_with_fields():
            full_name = f"{view.schema_name}.{view.view_name}"
            for field in fields:
                text = compact_lines(
                    [
                        "类型：字段",
                        f"视图：{full_name}",
                        f"字段：{field.field_name}",
                        f"字段类型：{field.field_type or ''}",
                        f"说明：{field.description or ''}",
                        f"是否维度：{field.is_dimension}",
                        f"是否指标：{field.is_measure}",
                        f"示例值：{field.example_value or ''}",
                    ]
                )
                values.append(
                    {
                        "metadata_type": "field",
                        "name": f"{full_name}.{field.field_name}",
                        "description": field.description,
                        "aliases_json": [field.field_name, field.example_value]
                        if field.example_value
                        else [field.field_name],
                        "business_meaning": field.description,
                        "related_table": full_name,
                        "related_field": field.field_name,
                        "ddl_snippet": f"{field.field_name} {field.field_type or 'text'}",
                        "embedding_text": text,
                        "search_text": text,
                        "metadata_json": {
                            "is_dimension": field.is_dimension,
                            "is_measure": field.is_measure,
                            "allowed_filter": field.allowed_filter,
                            "allowed_group_by": field.allowed_group_by,
                        },
                    }
                )
        return values

    def _metric_items(self) -> list[dict]:
        metrics = list(
            self.db.scalars(select(Metric).order_by(Metric.domain.asc(), Metric.indicator_code.asc()))
        )
        values = []
        for metric in metrics:
            related_table = METRIC_VIEW_BY_CODE.get(metric.indicator_code, "")
            aliases = unique_strings(
                [metric.indicator_name, metric.indicator_code, *(metric.aliases_json or [])]
            )
            related_field = "value_numeric" if related_table else ""
            text = compact_lines(
                [
                    "类型：指标",
                    f"名称：{metric.indicator_name}",
                    f"指标编码：{metric.indicator_code}",
                    f"别名：{'、'.join(aliases)}",
                    f"领域：{metric.domain}",
                    f"单位：{metric.unit or ''}",
                    f"说明：{metric.description or ''}",
                    f"可查询视图：{related_table}",
                    "相关字段：region_name, stat_year, value_numeric, unit",
                ]
            )
            values.append(
                {
                    "metadata_type": "metric",
                    "name": metric.indicator_name,
                    "description": metric.description,
                    "aliases_json": aliases,
                    "business_meaning": metric.description,
                    "related_table": related_table,
                    "related_field": related_field,
                    "unit": metric.unit,
                    "time_grain": "annual",
                    "embedding_text": text,
                    "search_text": text,
                    "metadata_json": {
                        "metric_id": str(metric.id),
                        "indicator_code": metric.indicator_code,
                        "domain": metric.domain,
                    },
                }
            )
        return values

    def _reporting_views_with_fields(self) -> list[tuple[ReportingView, list[ReportingViewField]]]:
        views = list(
            self.db.scalars(
                select(ReportingView)
                .where(ReportingView.enabled.is_(True))
                .order_by(ReportingView.schema_name.asc(), ReportingView.view_name.asc())
            )
        )
        result = []
        for view in views:
            fields = list(
                self.db.scalars(
                    select(ReportingViewField)
                    .where(ReportingViewField.view_id == view.id)
                    .order_by(ReportingViewField.field_name.asc())
                )
            )
            result.append((view, fields))
        return result


def normalize_metadata_types(metadata_types: list[str] | None) -> list[str]:
    if metadata_types is None:
        return DEFAULT_METADATA_TYPES.copy()
    normalized = []
    for metadata_type in metadata_types:
        if metadata_type not in SEMANTIC_METADATA_TYPES:
            raise SemanticMetadataError(f"Unsupported semantic metadata type: {metadata_type}")
        if metadata_type not in normalized:
            normalized.append(metadata_type)
    if not normalized:
        raise SemanticMetadataError("metadata types must not be empty")
    return normalized


def static_seed_to_values(seeds: tuple[StaticSemanticSeed, ...]) -> list[dict]:
    values = []
    for seed in seeds:
        text = compact_lines(
            [
                f"类型：{seed.metadata_type}",
                f"名称：{seed.name}",
                f"别名：{'、'.join(seed.aliases)}",
                f"说明：{seed.description}",
                f"业务口径：{seed.business_meaning or ''}",
                f"可查询视图：{seed.related_table}",
                f"相关字段：{seed.related_field}",
                f"SQL示例：{seed.sql_example or ''}",
            ]
        )
        values.append(
            {
                "metadata_type": seed.metadata_type,
                "name": seed.name,
                "description": seed.description,
                "aliases_json": list(seed.aliases),
                "business_meaning": seed.business_meaning,
                "related_table": seed.related_table,
                "related_field": seed.related_field,
                "unit": seed.unit,
                "time_grain": seed.time_grain,
                "ddl_snippet": seed.ddl_snippet,
                "sql_example": seed.sql_example,
                "join_path": seed.join_path,
                "embedding_text": text,
                "search_text": text,
                "metadata_json": seed.metadata_json or {},
            }
        )
    return values


def semantic_embedding_row(
    *,
    item: SemanticMetadataItem,
    vector: list[float],
    embedding_model: str,
    embedding_dim: int,
    embedding_version: str,
) -> dict:
    return {
        "metadata_item_id": item.id,
        "embedding_model": embedding_model,
        "embedding_dim": embedding_dim,
        "embedding_version": embedding_version,
        "embedding": [float(value) for value in vector],
    }


def batched(items: list[SemanticMetadataItem], batch_size: int) -> list[list[SemanticMetadataItem]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def compact_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line and not line.endswith("："))


def unique_strings(values: list[str | None]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if not value:
            continue
        stripped = str(value).strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
    return result
