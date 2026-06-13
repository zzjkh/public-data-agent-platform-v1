from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models.reporting import ReportingView, ReportingViewField
from app.db.models.semantic_metadata import SemanticMetadataItem
from app.llm.contracts import NormalizedTimeRange, SqlGenerationResult
from app.llm.prompts import PromptLoader
from app.llm.provider import LLMJsonResult
from app.semantic.retriever import RetrievedSemanticMetadata


SQL_GENERATION_SYSTEM_PROMPT = """你是公共数据开放智能知识与数据分析平台中的 Text-to-SQL 模块。
你只能根据输入中的候选 reporting schema、语义元数据和 SQL 示例生成查询。
不要编造视图名、字段名、指标或数值。
输出必须是合法 JSON object，不要使用 Markdown 代码块。"""

DEFAULT_SQL_CONSTRAINTS = """- 只能生成一个 PostgreSQL SELECT 语句。
- 只能访问候选 schema 中列出的 reporting 视图。
- 只能使用候选 schema 中列出的字段。
- 禁止 SELECT *。
- 必须包含 LIMIT，默认 LIMIT 100。
- 时间趋势默认按时间字段升序排序。
- 如果提供 normalized_time_range，必须优先使用其中的 start_year / end_year。
- 问题明确指定地区时必须生成地域过滤，禁止返回无地域条件的全量结果。
- “某省下辖各市/省内各市”必须使用 parent_region_name 和 region_level='city'，禁止靠城市名称枚举或名称后缀猜测。"""


class SQLGenerationError(ValueError):
    pass


class SQLGenerationProvider(Protocol):
    async def generate_json(
        self,
        *,
        purpose: str,
        prompt_name: str,
        prompt_version: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[SqlGenerationResult],
        temperature: float = 0.1,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
    ) -> LLMJsonResult[SqlGenerationResult]:
        raise NotImplementedError


@dataclass(frozen=True)
class SQLGenerationOutput:
    result: LLMJsonResult[SqlGenerationResult]
    candidate_schema: str
    semantic_hits_text: str
    sql_examples_text: str
    normalized_time_range_text: str


class SQLGenerator:
    def __init__(
        self,
        db: Session,
        *,
        provider: SQLGenerationProvider,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.db = db
        self.provider = provider
        self.prompt_loader = prompt_loader or PromptLoader()
        self.logger = get_logger()

    async def generate(
        self,
        *,
        question: str,
        semantic_hits: list[RetrievedSemanticMetadata],
        normalized_time_range: NormalizedTimeRange | None = None,
        constraints: str = DEFAULT_SQL_CONSTRAINTS,
    ) -> SQLGenerationOutput:
        normalized_question = question.strip()
        if not normalized_question:
            raise SQLGenerationError("question must not be empty")
        if not semantic_hits:
            raise SQLGenerationError("semantic_hits must not be empty")

        candidate_views = load_candidate_reporting_views(self.db, semantic_hits=semantic_hits)
        if not candidate_views:
            raise SQLGenerationError("No candidate reporting views found from semantic hits")

        candidate_schema = render_candidate_schema(candidate_views)
        semantic_hits_text = render_semantic_hits(semantic_hits)
        sql_examples_text = render_sql_examples(semantic_hits)
        normalized_time_range_text = render_normalized_time_range(normalized_time_range)

        template = self.prompt_loader.load("sql_generation")
        user_prompt = template.render(
            question=normalized_question,
            candidate_schema=candidate_schema,
            semantic_hits=semantic_hits_text,
            sql_examples=sql_examples_text,
            constraints=constraints,
            normalized_time_range=normalized_time_range_text,
        )
        result = await self.provider.generate_json(
            purpose=template.purpose,
            prompt_name=template.prompt_name,
            prompt_version=template.prompt_version,
            system_prompt=SQL_GENERATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=SqlGenerationResult,
            temperature=0.0,
        )
        result, unknown_metadata_ids = sanitize_used_metadata_ids(
            result,
            allowed_metadata_ids={str(hit.item.id) for hit in semantic_hits},
        )
        if unknown_metadata_ids:
            self.logger.warning(
                "sql_generation_unknown_metadata_ids_filtered",
                unknown_metadata_ids=unknown_metadata_ids,
                prompt_name=result.prompt_name,
                prompt_version=result.prompt_version,
                model_name=result.model_name,
            )
        validate_sql_generation_result(
            result.parsed,
            candidate_view_names=[view.full_name for view in candidate_views],
            normalized_time_range=normalized_time_range,
        )
        return SQLGenerationOutput(
            result=result,
            candidate_schema=candidate_schema,
            semantic_hits_text=semantic_hits_text,
            sql_examples_text=sql_examples_text,
            normalized_time_range_text=normalized_time_range_text,
        )


@dataclass(frozen=True)
class CandidateReportingView:
    schema_name: str
    view_name: str
    description: str | None
    fields: list[ReportingViewField]

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.view_name}"


def load_candidate_reporting_views(
    db: Session,
    *,
    semantic_hits: list[RetrievedSemanticMetadata],
) -> list[CandidateReportingView]:
    related_tables = unique_reporting_tables(hit.item.related_table for hit in semantic_hits)
    if not related_tables:
        return []

    candidates: list[CandidateReportingView] = []
    for full_name in related_tables:
        schema_name, view_name = full_name.split(".", 1)
        view = db.scalar(
            select(ReportingView).where(
                ReportingView.schema_name == schema_name,
                ReportingView.view_name == view_name,
                ReportingView.enabled.is_(True),
            )
        )
        if view is None:
            continue
        fields = list(
            db.scalars(
                select(ReportingViewField)
                .where(ReportingViewField.view_id == view.id)
                .order_by(ReportingViewField.field_name.asc())
            )
        )
        if fields:
            candidates.append(
                CandidateReportingView(
                    schema_name=view.schema_name,
                    view_name=view.view_name,
                    description=view.description,
                    fields=fields,
                )
            )
    return candidates


def unique_reporting_tables(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        table_name = str(value or "").strip()
        if not table_name.startswith("reporting.") or table_name.count(".") != 1:
            continue
        if table_name not in seen:
            seen.add(table_name)
            result.append(table_name)
    return result


def render_candidate_schema(views: list[CandidateReportingView]) -> str:
    blocks = ["可用 reporting 视图："]
    for index, view in enumerate(views, start=1):
        blocks.append(f"{index}. {view.full_name}")
        if view.description:
            blocks.append(f"   说明：{view.description}")
        blocks.append("   字段：")
        for field in view.fields:
            markers = []
            if field.is_dimension:
                markers.append("dimension")
            if field.is_measure:
                markers.append("measure")
            marker_text = f" [{' / '.join(markers)}]" if markers else ""
            example_text = f"，示例：{field.example_value}" if field.example_value else ""
            blocks.append(
                f"   - {field.field_name}: {field.field_type or 'text'}{marker_text}，"
                f"{field.description or ''}{example_text}"
            )
    return "\n".join(blocks)


def render_semantic_hits(semantic_hits: list[RetrievedSemanticMetadata]) -> str:
    lines = []
    for index, hit in enumerate(semantic_hits, start=1):
        item = hit.item
        lines.append(
            "\n".join(
                [
                    f"{index}. metadata_id: {item.id}",
                    f"   metadata_type: {item.metadata_type}",
                    f"   name: {item.name}",
                    f"   score: {hit.final_score:.4f}",
                    f"   related_table: {item.related_table}",
                    f"   related_field: {item.related_field}",
                    f"   unit: {item.unit or ''}",
                    f"   description: {item.description or ''}",
                ]
            )
        )
    return "\n".join(lines)


def render_sql_examples(semantic_hits: list[RetrievedSemanticMetadata]) -> str:
    examples = []
    for hit in semantic_hits:
        item = hit.item
        if item.metadata_type == "sql_example" and item.sql_example:
            examples.append(f"- {item.name}: {item.sql_example}")
    return "\n".join(examples) if examples else "无可用 SQL 示例。"


def render_normalized_time_range(normalized_time_range: NormalizedTimeRange | None) -> str:
    if normalized_time_range is None:
        return "null"
    return json.dumps(normalized_time_range.model_dump(mode="json"), ensure_ascii=False)


def validate_sql_generation_result(
    result: SqlGenerationResult,
    *,
    candidate_view_names: list[str],
    normalized_time_range: NormalizedTimeRange | None,
) -> None:
    sql = result.sql.strip()
    if contains_select_star(sql):
        raise SQLGenerationError("Generated SQL must not use SELECT *")
    if not references_candidate_view(sql=sql, candidate_view_names=candidate_view_names):
        raise SQLGenerationError("Generated SQL does not reference any candidate reporting view")
    validate_time_range_usage(sql=sql, normalized_time_range=normalized_time_range)


def sanitize_used_metadata_ids(
    result: LLMJsonResult[SqlGenerationResult],
    *,
    allowed_metadata_ids: set[str],
) -> tuple[LLMJsonResult[SqlGenerationResult], list[str]]:
    valid_ids = [
        metadata_id
        for metadata_id in result.parsed.used_metadata_ids
        if metadata_id in allowed_metadata_ids
    ]
    unknown_ids = [
        metadata_id
        for metadata_id in result.parsed.used_metadata_ids
        if metadata_id not in allowed_metadata_ids
    ]
    if not unknown_ids:
        return result, []
    return (
        replace(
            result,
            parsed=result.parsed.model_copy(update={"used_metadata_ids": valid_ids}),
        ),
        unknown_ids,
    )


def contains_select_star(sql: str) -> bool:
    normalized = re.sub(r"\s+", " ", sql.strip().lower())
    return bool(re.search(r"\bselect\s+(?:distinct\s+)?(?:\*|[\w]+\.\*)", normalized))


def references_candidate_view(*, sql: str, candidate_view_names: list[str]) -> bool:
    lowered = sql.lower()
    return any(view_name.lower() in lowered for view_name in candidate_view_names)


def validate_time_range_usage(
    *,
    sql: str,
    normalized_time_range: NormalizedTimeRange | None,
) -> None:
    if normalized_time_range is None:
        return
    required_years = [
        year
        for year in (normalized_time_range.start_year, normalized_time_range.end_year)
        if year is not None
    ]
    missing_years = [str(year) for year in required_years if str(year) not in sql]
    if missing_years:
        raise SQLGenerationError(
            "Generated SQL does not use normalized_time_range years: " + ", ".join(missing_years)
        )


def semantic_hit_from_item(
    item: SemanticMetadataItem,
    *,
    final_score: float = 1.0,
) -> RetrievedSemanticMetadata:
    return RetrievedSemanticMetadata(item=item, final_score=final_score, match_sources=["manual"])
