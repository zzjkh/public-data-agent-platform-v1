from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


RouteType = Literal["POLICY_QA", "DATA_QA", "HYBRID_QA", "OTHER"]
ChartType = Literal["line", "bar", "pie", "table"]


class NormalizedTimeRange(BaseModel):
    start_year: int | None = None
    end_year: int | None = None
    grain: Literal["year", "month", "day"] | None = None
    source_text: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtractedEntities(BaseModel):
    region: str | None = None
    time_range: str | None = None
    normalized_time_range: NormalizedTimeRange | None = None
    metrics: list[str] = Field(default_factory=list)
    policy_topics: list[str] = Field(default_factory=list)


class QuestionRoute(BaseModel):
    route_type: RouteType
    needs_policy_evidence: bool
    needs_data_analysis: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    extracted_entities: ExtractedEntities = Field(default_factory=ExtractedEntities)


class PolicyCitation(BaseModel):
    source_id: str
    source_title: str
    source_url: str | None = None
    section_path: str | None = None
    quote: str


class RagAnswer(BaseModel):
    answer: str
    evidence_sufficient: bool
    citations: list[PolicyCitation] = Field(default_factory=list)
    caveat: str | None = None
    suggested_followups: list[str] = Field(default_factory=list)


class SqlGenerationResult(BaseModel):
    sql: str
    reason: str
    used_metadata_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("sql")
    @classmethod
    def sql_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sql must not be empty")
        return value.strip()


class DataSourceCitation(BaseModel):
    title: str
    source_url: str | None = None


class SqlResultExplanation(BaseModel):
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    data_sources: list[DataSourceCitation] = Field(default_factory=list)
    caveat: str | None = None


class ChartSpec(BaseModel):
    chart_type: ChartType
    x_field: str | None = None
    y_field: str | None = None
    series_field: str | None = None
    title: str
    reason: str


class HybridPolicyCitation(BaseModel):
    source_title: str
    source_url: str | None = None
    section_path: str | None = None
    quote: str


class HybridAnswer(BaseModel):
    answer: str
    policy_citations: list[HybridPolicyCitation] = Field(default_factory=list)
    data_sources: list[DataSourceCitation] = Field(default_factory=list)
    used_sql: bool
    used_policy_evidence: bool
    caveat: str | None = None


CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    "QuestionRoute": QuestionRoute,
    "RagAnswer": RagAnswer,
    "SqlGenerationResult": SqlGenerationResult,
    "SqlResultExplanation": SqlResultExplanation,
    "ChartSpec": ChartSpec,
    "HybridAnswer": HybridAnswer,
}


def get_contract_model(name: str) -> type[BaseModel]:
    try:
        return CONTRACT_MODELS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown LLM contract model: {name}") from exc
