from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5


REPORTING_METADATA_NAMESPACE = UUID("8f0fb2dd-d5ea-42a6-a47a-9199b7e8d901")


@dataclass(frozen=True)
class ReportingFieldSeed:
    field_name: str
    field_type: str
    description: str
    is_dimension: bool = False
    is_measure: bool = False
    allowed_filter: bool = True
    allowed_group_by: bool = False
    example_value: str | None = None


@dataclass(frozen=True)
class ReportingViewSeed:
    schema_name: str
    view_name: str
    description: str
    fields: tuple[ReportingFieldSeed, ...]

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.view_name}"

    @property
    def id(self) -> UUID:
        return uuid5(REPORTING_METADATA_NAMESPACE, self.full_name)


def make_field_id(view: ReportingViewSeed, field_name: str) -> UUID:
    return uuid5(REPORTING_METADATA_NAMESPACE, f"{view.full_name}.{field_name}")


METRIC_YEARLY_FIELDS: tuple[ReportingFieldSeed, ...] = (
    ReportingFieldSeed(
        "region_code",
        "text",
        "行政区划代码，用于稳定识别地区。",
        is_dimension=True,
        example_value="330100",
    ),
    ReportingFieldSeed(
        "region_level",
        "text",
        "行政区层级，例如 province、city、district。",
        is_dimension=True,
        allowed_group_by=True,
        example_value="city",
    ),
    ReportingFieldSeed(
        "parent_region_name",
        "text",
        "上级行政区名称，用于省内城市或市内区县过滤。",
        is_dimension=True,
        allowed_group_by=True,
        example_value="浙江省",
    ),
    ReportingFieldSeed(
        "parent_region_code",
        "text",
        "上级行政区划代码。",
        is_dimension=True,
        example_value="330000",
    ),
    ReportingFieldSeed(
        "region_name",
        "text",
        "行政区名称，用于按地区过滤或分组。",
        is_dimension=True,
        allowed_group_by=True,
        example_value="北京市",
    ),
    ReportingFieldSeed(
        "stat_year",
        "integer",
        "统计年份，适合处理近五年、某一年等时间条件。",
        is_dimension=True,
        allowed_group_by=True,
        example_value="2024",
    ),
    ReportingFieldSeed(
        "indicator_name",
        "text",
        "指标中文名称。",
        is_dimension=True,
        allowed_group_by=True,
        example_value="常住人口",
    ),
    ReportingFieldSeed(
        "value_numeric",
        "numeric",
        "指标数值。生成趋势或排名解释时必须结合 unit 字段理解单位。",
        is_measure=True,
        example_value="2183.2",
    ),
    ReportingFieldSeed(
        "unit",
        "text",
        "指标单位，例如万人、亿元。",
        is_dimension=True,
        allowed_group_by=True,
        example_value="万人",
    ),
    ReportingFieldSeed(
        "source",
        "text",
        "数据来源名称。",
        is_dimension=True,
        example_value="北京市统计公报",
    ),
    ReportingFieldSeed(
        "source_url",
        "text",
        "数据来源链接，用于回答中的引用和溯源。",
        is_dimension=True,
        example_value="https://example.com/source",
    ),
    ReportingFieldSeed(
        "data_version",
        "text",
        "数据版本，用于区分统计公报、样例数据或后续修订数据。",
        is_dimension=True,
        example_value="v1",
    ),
)


REPORTING_VIEW_SEEDS: tuple[ReportingViewSeed, ...] = (
    ReportingViewSeed(
        schema_name="reporting",
        view_name="vw_population_yearly",
        description="年度常住人口指标视图，仅包含年度统计口径的数据。",
        fields=METRIC_YEARLY_FIELDS,
    ),
    ReportingViewSeed(
        schema_name="reporting",
        view_name="vw_gdp_yearly",
        description="年度地区生产总值指标视图，仅包含年度统计口径的数据。",
        fields=METRIC_YEARLY_FIELDS,
    ),
    ReportingViewSeed(
        schema_name="reporting",
        view_name="vw_dataset_catalog",
        description="开放数据目录明细视图，仅暴露 active 状态的数据集。",
        fields=(
            ReportingFieldSeed(
                "dataset_name",
                "text",
                "数据集名称。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="北京市公共数据开放平台目录",
            ),
            ReportingFieldSeed(
                "category",
                "text",
                "数据集所属主题分类。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="公共数据目录",
            ),
            ReportingFieldSeed(
                "department",
                "text",
                "数据提供部门。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="北京市经济和信息化局",
            ),
            ReportingFieldSeed(
                "open_type",
                "text",
                "开放类型，例如无条件开放。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="无条件开放",
            ),
            ReportingFieldSeed(
                "update_date",
                "date",
                "数据集最近更新日期。",
                is_dimension=True,
                example_value="2026-05-29",
            ),
            ReportingFieldSeed(
                "download_count",
                "integer",
                "数据集下载次数。",
                is_measure=True,
                example_value="4457",
            ),
            ReportingFieldSeed(
                "api_count",
                "integer",
                "数据集关联接口数量。",
                is_measure=True,
                example_value="4457",
            ),
            ReportingFieldSeed(
                "source_platform",
                "text",
                "数据来源平台。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="北京市公共数据开放平台",
            ),
            ReportingFieldSeed(
                "source_url",
                "text",
                "数据集来源页面链接。",
                is_dimension=True,
                example_value="https://data.example.gov.cn/catalog",
            ),
            ReportingFieldSeed(
                "update_frequency",
                "text",
                "数据集更新频率。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="年度",
            ),
            ReportingFieldSeed(
                "status",
                "text",
                "数据集状态。该视图默认仅包含 active 数据。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="active",
            ),
        ),
    ),
    ReportingViewSeed(
        schema_name="reporting",
        view_name="vw_dataset_category_stats",
        description="按主题分类聚合的开放数据目录统计视图。",
        fields=(
            ReportingFieldSeed(
                "category",
                "text",
                "数据集所属主题分类。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="公共数据目录",
            ),
            ReportingFieldSeed(
                "dataset_count",
                "integer",
                "该分类下 active 数据集数量。",
                is_measure=True,
                example_value="12",
            ),
            ReportingFieldSeed(
                "api_count",
                "integer",
                "该分类下 active 数据集关联接口总数。",
                is_measure=True,
                example_value="48",
            ),
            ReportingFieldSeed(
                "latest_update_date",
                "date",
                "该分类下数据集最近一次更新日期。",
                is_dimension=True,
                example_value="2026-05-29",
            ),
        ),
    ),
    ReportingViewSeed(
        schema_name="reporting",
        view_name="vw_dataset_department_stats",
        description="按提供部门聚合的开放数据目录统计视图。",
        fields=(
            ReportingFieldSeed(
                "department",
                "text",
                "数据提供部门。",
                is_dimension=True,
                allowed_group_by=True,
                example_value="北京市经济和信息化局",
            ),
            ReportingFieldSeed(
                "dataset_count",
                "integer",
                "该部门 active 数据集数量。",
                is_measure=True,
                example_value="12",
            ),
            ReportingFieldSeed(
                "api_count",
                "integer",
                "该部门 active 数据集关联接口总数。",
                is_measure=True,
                example_value="48",
            ),
            ReportingFieldSeed(
                "latest_update_date",
                "date",
                "该部门数据集最近一次更新日期。",
                is_dimension=True,
                example_value="2026-05-29",
            ),
        ),
    ),
)

REPORTING_VIEW_NAMES = tuple(view.full_name for view in REPORTING_VIEW_SEEDS)
