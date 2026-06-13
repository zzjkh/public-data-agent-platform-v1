"""reporting views metadata

Revision ID: 008_reporting_views_metadata
Revises: 007_metric_values_source_url
Create Date: 2026-06-01
"""
from __future__ import annotations

from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa

revision = "008_reporting_views_metadata"
down_revision = "007_metric_values_source_url"
branch_labels = None
depends_on = None

REPORTING_METADATA_NAMESPACE = UUID("8f0fb2dd-d5ea-42a6-a47a-9199b7e8d901")


def _view_id(schema_name: str, view_name: str) -> UUID:
    return uuid5(REPORTING_METADATA_NAMESPACE, f"{schema_name}.{view_name}")


def _field_id(schema_name: str, view_name: str, field_name: str) -> UUID:
    return uuid5(REPORTING_METADATA_NAMESPACE, f"{schema_name}.{view_name}.{field_name}")


METRIC_YEARLY_FIELDS = (
    ("region_name", "text", "行政区名称，用于按地区过滤或分组。", True, False, True, True, "北京市"),
    ("stat_year", "integer", "统计年份，适合处理近五年、某一年等时间条件。", True, False, True, True, "2024"),
    ("indicator_name", "text", "指标中文名称。", True, False, True, True, "常住人口"),
    ("value_numeric", "numeric", "指标数值。生成趋势或排名解释时必须结合 unit 字段理解单位。", False, True, True, False, "2183.2"),
    ("unit", "text", "指标单位，例如万人、亿元。", True, False, True, True, "万人"),
    ("source", "text", "数据来源名称。", True, False, True, False, "北京市统计公报"),
    ("source_url", "text", "数据来源链接，用于回答中的引用和溯源。", True, False, True, False, "https://example.com/source"),
    ("data_version", "text", "数据版本，用于区分统计公报、样例数据或后续修订数据。", True, False, True, False, "v1"),
)

VIEW_SEEDS = (
    (
        "reporting",
        "vw_population_yearly",
        "年度常住人口指标视图，仅包含年度统计口径的数据。",
        METRIC_YEARLY_FIELDS,
    ),
    (
        "reporting",
        "vw_gdp_yearly",
        "年度地区生产总值指标视图，仅包含年度统计口径的数据。",
        METRIC_YEARLY_FIELDS,
    ),
    (
        "reporting",
        "vw_dataset_catalog",
        "开放数据目录明细视图，仅暴露 active 状态的数据集。",
        (
            ("dataset_name", "text", "数据集名称。", True, False, True, True, "北京市公共数据开放平台目录"),
            ("category", "text", "数据集所属主题分类。", True, False, True, True, "公共数据目录"),
            ("department", "text", "数据提供部门。", True, False, True, True, "北京市经济和信息化局"),
            ("open_type", "text", "开放类型，例如无条件开放。", True, False, True, True, "无条件开放"),
            ("update_date", "date", "数据集最近更新日期。", True, False, True, False, "2026-05-29"),
            ("download_count", "integer", "数据集下载次数。", False, True, True, False, "4457"),
            ("api_count", "integer", "数据集关联接口数量。", False, True, True, False, "4457"),
            ("source_platform", "text", "数据来源平台。", True, False, True, True, "北京市公共数据开放平台"),
            ("source_url", "text", "数据集来源页面链接。", True, False, True, False, "https://data.example.gov.cn/catalog"),
            ("update_frequency", "text", "数据集更新频率。", True, False, True, True, "年度"),
            ("status", "text", "数据集状态。该视图默认仅包含 active 数据。", True, False, True, True, "active"),
        ),
    ),
    (
        "reporting",
        "vw_dataset_category_stats",
        "按主题分类聚合的开放数据目录统计视图。",
        (
            ("category", "text", "数据集所属主题分类。", True, False, True, True, "公共数据目录"),
            ("dataset_count", "integer", "该分类下 active 数据集数量。", False, True, True, False, "12"),
            ("api_count", "integer", "该分类下 active 数据集关联接口总数。", False, True, True, False, "48"),
            ("latest_update_date", "date", "该分类下数据集最近一次更新日期。", True, False, True, False, "2026-05-29"),
        ),
    ),
    (
        "reporting",
        "vw_dataset_department_stats",
        "按提供部门聚合的开放数据目录统计视图。",
        (
            ("department", "text", "数据提供部门。", True, False, True, True, "北京市经济和信息化局"),
            ("dataset_count", "integer", "该部门 active 数据集数量。", False, True, True, False, "12"),
            ("api_count", "integer", "该部门 active 数据集关联接口总数。", False, True, True, False, "48"),
            ("latest_update_date", "date", "该部门数据集最近一次更新日期。", True, False, True, False, "2026-05-29"),
        ),
    ),
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reporting")
    op.create_table(
        "reporting_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_name", sa.String(length=64), server_default="reporting", nullable=False),
        sa.Column("view_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schema_name", "view_name", name="uq_reporting_views_schema_view"),
    )
    op.create_index("ix_reporting_views_enabled", "reporting_views", ["enabled"], unique=False)

    op.create_table(
        "reporting_view_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("view_id", sa.Uuid(), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("field_type", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_dimension", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_measure", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allowed_filter", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("allowed_group_by", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("example_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["view_id"], ["reporting_views.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("view_id", "field_name", name="uq_reporting_view_fields_view_field"),
    )
    op.create_index("ix_reporting_view_fields_view_id", "reporting_view_fields", ["view_id"], unique=False)

    _create_reporting_views()
    _seed_reporting_metadata()
    _grant_reporting_readonly_if_role_exists()


def downgrade() -> None:
    op.drop_index("ix_reporting_view_fields_view_id", table_name="reporting_view_fields")
    op.drop_table("reporting_view_fields")
    op.drop_index("ix_reporting_views_enabled", table_name="reporting_views")
    op.drop_table("reporting_views")

    for view_name in (
        "vw_dataset_department_stats",
        "vw_dataset_category_stats",
        "vw_dataset_catalog",
        "vw_gdp_yearly",
        "vw_population_yearly",
    ):
        op.execute(f"DROP VIEW IF EXISTS reporting.{view_name}")


def _create_reporting_views() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW reporting.vw_population_yearly AS
        SELECT
          mv.region_name,
          mv.stat_year,
          m.indicator_name,
          mv.value_numeric,
          mv.unit,
          mv.source,
          mv.source_url,
          mv.data_version
        FROM metric_values mv
        JOIN metrics m ON mv.metric_id = m.id
        WHERE m.indicator_code = 'resident_population'
          AND mv.stat_period = 'annual'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW reporting.vw_gdp_yearly AS
        SELECT
          mv.region_name,
          mv.stat_year,
          m.indicator_name,
          mv.value_numeric,
          mv.unit,
          mv.source,
          mv.source_url,
          mv.data_version
        FROM metric_values mv
        JOIN metrics m ON mv.metric_id = m.id
        WHERE m.indicator_code = 'gdp_total'
          AND mv.stat_period = 'annual'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW reporting.vw_dataset_catalog AS
        SELECT
          name AS dataset_name,
          category,
          department,
          open_type,
          update_date,
          download_count,
          api_count,
          source_platform,
          source_url,
          update_frequency,
          status
        FROM open_datasets
        WHERE status = 'active'
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW reporting.vw_dataset_category_stats AS
        SELECT
          category,
          COUNT(*) AS dataset_count,
          COALESCE(SUM(api_count), 0) AS api_count,
          MAX(update_date) AS latest_update_date
        FROM open_datasets
        WHERE status = 'active'
        GROUP BY category
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW reporting.vw_dataset_department_stats AS
        SELECT
          department,
          COUNT(*) AS dataset_count,
          COALESCE(SUM(api_count), 0) AS api_count,
          MAX(update_date) AS latest_update_date
        FROM open_datasets
        WHERE status = 'active'
        GROUP BY department
        """
    )


def _seed_reporting_metadata() -> None:
    reporting_views = sa.table(
        "reporting_views",
        sa.column("id", sa.Uuid()),
        sa.column("schema_name", sa.String()),
        sa.column("view_name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("enabled", sa.Boolean()),
    )
    reporting_view_fields = sa.table(
        "reporting_view_fields",
        sa.column("id", sa.Uuid()),
        sa.column("view_id", sa.Uuid()),
        sa.column("field_name", sa.String()),
        sa.column("field_type", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_dimension", sa.Boolean()),
        sa.column("is_measure", sa.Boolean()),
        sa.column("allowed_filter", sa.Boolean()),
        sa.column("allowed_group_by", sa.Boolean()),
        sa.column("example_value", sa.Text()),
    )

    view_rows = []
    field_rows = []
    for schema_name, view_name, description, fields in VIEW_SEEDS:
        view_uuid = _view_id(schema_name, view_name)
        view_rows.append(
            {
                "id": view_uuid,
                "schema_name": schema_name,
                "view_name": view_name,
                "description": description,
                "enabled": True,
            }
        )
        for (
            field_name,
            field_type,
            field_description,
            is_dimension,
            is_measure,
            allowed_filter,
            allowed_group_by,
            example_value,
        ) in fields:
            field_rows.append(
                {
                    "id": _field_id(schema_name, view_name, field_name),
                    "view_id": view_uuid,
                    "field_name": field_name,
                    "field_type": field_type,
                    "description": field_description,
                    "is_dimension": is_dimension,
                    "is_measure": is_measure,
                    "allowed_filter": allowed_filter,
                    "allowed_group_by": allowed_group_by,
                    "example_value": example_value,
                }
            )

    op.bulk_insert(reporting_views, view_rows)
    op.bulk_insert(reporting_view_fields, field_rows)


def _grant_reporting_readonly_if_role_exists() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA reporting TO app_readonly';
            EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO app_readonly';
          END IF;
        END
        $$;
        """
    )
