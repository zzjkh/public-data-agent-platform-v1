from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.analytics.sql_executor import SQLExecutionResult, SQLExecutor
from app.analytics.sql_generator import SQLGenerationOutput, SQLGenerator
from app.analytics.sql_guard import SQLGuard, SQLGuardResult
from app.core.config import Settings
from app.llm.contracts import (
    ChartSpec,
    HybridAnswer,
    QuestionRoute,
    RagAnswer,
    RouteType,
    SqlResultExplanation,
)
from app.llm.embedding_provider import EmbeddingProvider
from app.llm.prompts import PromptLoader
from app.llm.provider import LLMJsonResult
from app.qa.router import QuestionRouter
from app.qa.schemas import QaCitation, QaResponse, QaSqlPayload
from app.qa.security import QuestionSecurityPolicy
from app.rag.context_builder import ContextBuilder, PolicyContext
from app.rag.retriever import PolicyRetrievalResult, PolicyRetriever
from app.semantic.retriever import SemanticMetadataRetriever, SemanticRetrievalResult
from app.trace.service import TraceService


T = TypeVar("T", bound=BaseModel)

RAG_ANSWER_SYSTEM_PROMPT = """你是公共数据开放智能知识与数据分析平台中的政策问答模块。
你只能根据输入的政策资料回答，不能编造来源。
输出必须是合法 JSON object，不要使用 Markdown 代码块。"""

SQL_RESULT_EXPLANATION_SYSTEM_PROMPT = """你是公共数据开放智能知识与数据分析平台中的数据分析解释模块。
你只能解释输入 SQL 结果中存在的数据，不要编造未返回的数值。
输出必须是合法 JSON object，不要使用 Markdown 代码块。"""

CHART_RECOMMENDATION_SYSTEM_PROMPT = """你是公共数据开放智能知识与数据分析平台中的图表推荐模块。
你只能从输入字段中选择图表字段。
输出必须是合法 JSON object，不要使用 Markdown 代码块。"""

HYBRID_ANSWER_SYSTEM_PROMPT = """你是公共数据开放智能知识与数据分析平台中的复合问答模块。
你需要综合政策依据和结构化数据结果，但不能混淆政策结论与数据趋势。
输出必须是合法 JSON object，不要使用 Markdown 代码块。"""

SEMANTIC_METADATA_TYPES = ["dataset", "table", "field", "metric", "sql_example", "business_rule"]
POLICY_TOPIC_EXPANSIONS = {
    "公共数据开放": ("公共数据资源",),
    "个人信息保护": ("个人信息", "个人隐私"),
    "数据安全": ("分类分级",),
}


class QAOrchestrationError(RuntimeError):
    pass


class QAProvider(Protocol):
    async def generate_json(
        self,
        *,
        purpose: str,
        prompt_name: str,
        prompt_version: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        temperature: float = 0.1,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
    ) -> LLMJsonResult[T]:
        raise NotImplementedError


@dataclass(frozen=True)
class PolicyPipelineOutput:
    retrieval: PolicyRetrievalResult
    context: PolicyContext
    answer_result: LLMJsonResult[RagAnswer]


@dataclass(frozen=True)
class DataPipelineOutput:
    semantic_retrieval: SemanticRetrievalResult
    sql_generation: SQLGenerationOutput
    sql_guard: SQLGuardResult
    sql_execution: SQLExecutionResult
    explanation_result: LLMJsonResult[SqlResultExplanation]
    chart_result: LLMJsonResult[ChartSpec]


class QAOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        settings: Settings,
        provider: QAProvider,
        embedding_provider: EmbeddingProvider,
        sql_executor: SQLExecutor | None = None,
        prompt_loader: PromptLoader | None = None,
        trace_service: TraceService | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.provider = provider
        self.embedding_provider = embedding_provider
        self.sql_executor = sql_executor or SQLExecutor(settings=settings)
        self.prompt_loader = prompt_loader or PromptLoader()
        self.trace_service = trace_service or TraceService(db)

    async def ask(
        self,
        *,
        question: str,
        user_id: UUID | None,
        request_id: str,
        current_date: date | None = None,
    ) -> QaResponse:
        normalized_question = question.strip()
        if not normalized_question:
            raise QAOrchestrationError("question must not be empty")

        trace_started = perf_counter()
        trace = self.trace_service.create_trace(user_id=user_id, question=normalized_question)
        route_type: RouteType | None = None
        final_answer = ""
        try:
            safety_started = perf_counter()
            safety_decision = QuestionSecurityPolicy().evaluate(normalized_question)
            self.trace_service.add_span(
                trace_id=trace.id,
                span_type="safety_guard",
                input_json={"question": normalized_question},
                output_json={
                    "allowed": safety_decision.allowed,
                    "code": safety_decision.code,
                    "category": safety_decision.category,
                },
                latency_ms=elapsed_ms(safety_started),
                status="success",
            )
            if not safety_decision.allowed:
                route_type = "OTHER"
                response = QaResponse(
                    trace_id=trace.id,
                    route_type=route_type,
                    answer=safety_decision.response_message or "该请求无法处理。",
                    citations=[],
                    sql=None,
                    chart=None,
                    request_id=request_id,
                )
                final_answer = response.answer
                self.trace_service.finish_trace(
                    trace_id=trace.id,
                    route_type=route_type,
                    final_answer=final_answer,
                    status="refused",
                    latency_ms=elapsed_ms(trace_started),
                )
                self.db.commit()
                return response

            route_result = await self._route_question(
                trace_id=trace.id,
                question=normalized_question,
                current_date=current_date,
            )
            route = route_result.parsed
            route_type = route.route_type
            policy_retrieval_query = build_policy_retrieval_query(
                question=normalized_question,
                route=route,
            )

            if route.route_type == "POLICY_QA":
                policy = await self._run_policy_pipeline(
                    trace_id=trace.id,
                    question=normalized_question,
                    retrieval_query=policy_retrieval_query,
                )
                response = self._policy_response(
                    trace_id=trace.id,
                    request_id=request_id,
                    route_type=route.route_type,
                    policy=policy,
                )
            elif route.route_type == "DATA_QA":
                data = await self._run_data_pipeline(
                    trace_id=trace.id,
                    question=normalized_question,
                    route=route,
                )
                response = self._data_response(
                    trace_id=trace.id,
                    request_id=request_id,
                    route_type=route.route_type,
                    data=data,
                )
            elif route.route_type == "HYBRID_QA":
                policy = await self._run_policy_pipeline(
                    trace_id=trace.id,
                    question=normalized_question,
                    retrieval_query=policy_retrieval_query,
                )
                data = await self._run_data_pipeline(
                    trace_id=trace.id,
                    question=normalized_question,
                    route=route,
                )
                hybrid_result = await self._generate_hybrid_answer(
                    trace_id=trace.id,
                    question=normalized_question,
                    policy=policy,
                    data=data,
                )
                response = self._hybrid_response(
                    trace_id=trace.id,
                    request_id=request_id,
                    route_type=route.route_type,
                    hybrid=hybrid_result,
                    data=data,
                )
            else:
                response = QaResponse(
                    trace_id=trace.id,
                    route_type=route.route_type,
                    answer=route.reason,
                    citations=[],
                    sql=None,
                    chart=None,
                    request_id=request_id,
                )

            final_answer = response.answer
            self.trace_service.finish_trace(
                trace_id=trace.id,
                route_type=route_type,
                final_answer=final_answer,
                status="refused" if route_type == "OTHER" else "success",
                latency_ms=elapsed_ms(trace_started),
            )
            self.db.commit()
            return response
        except Exception as exc:
            self.trace_service.add_span(
                trace_id=trace.id,
                span_type="orchestrator",
                input_json={"question": normalized_question},
                output_json=None,
                latency_ms=elapsed_ms(trace_started),
                status="failed",
                error_message=str(exc),
            )
            self.trace_service.finish_trace(
                trace_id=trace.id,
                route_type=route_type,
                final_answer=final_answer,
                status="failed",
                latency_ms=elapsed_ms(trace_started),
            )
            self.db.commit()
            raise

    async def _route_question(
        self,
        *,
        trace_id: UUID,
        question: str,
        current_date: date | None,
    ) -> LLMJsonResult[QuestionRoute]:
        result = await QuestionRouter(provider=self.provider, prompt_loader=self.prompt_loader).route(
            question=question,
            current_date=current_date,
        )
        self._add_llm_span(
            trace_id=trace_id,
            span_type="router",
            result=result,
            input_json={"question": question},
            output_json=result.parsed.model_dump(mode="json"),
        )
        return result

    async def _run_policy_pipeline(
        self,
        *,
        trace_id: UUID,
        question: str,
        retrieval_query: str,
    ) -> PolicyPipelineOutput:
        started = perf_counter()
        retrieval = PolicyRetriever(self.db).retrieve(
            query=retrieval_query,
            embedding_provider=self.embedding_provider,
            embedding_model=self.settings.embedding_model,
            embedding_version=self.settings.embedding_version,
        )
        context = ContextBuilder().build(retrieval.chunks)
        self.trace_service.add_span(
            trace_id=trace_id,
            span_type="policy_retrieval",
            input_json={
                "query": retrieval_query,
                "original_question": question,
                **retrieval_trace_config(self.settings),
            },
            output_json={
                "chunk_count": len(retrieval.chunks),
                "source_counts": retrieval_source_counts(retrieval.chunks),
                "chunks": [chunk_to_trace(chunk) for chunk in retrieval.chunks],
            },
            latency_ms=elapsed_ms(started),
            status="success",
        )

        template = self.prompt_loader.load("rag_answer")
        result = await self.provider.generate_json(
            purpose=template.purpose,
            prompt_name=template.prompt_name,
            prompt_version=template.prompt_version,
            system_prompt=RAG_ANSWER_SYSTEM_PROMPT,
            user_prompt=template.render(
                question=question,
                evidence_blocks=context.context_text,
            ),
            response_model=RagAnswer,
            temperature=0.0,
        )
        self._add_llm_span(
            trace_id=trace_id,
            span_type="answer_generation",
            result=result,
            input_json={"question": question, "evidence_block_count": len(context.evidence_blocks)},
            output_json=result.parsed.model_dump(mode="json"),
        )
        return PolicyPipelineOutput(retrieval=retrieval, context=context, answer_result=result)

    async def _run_data_pipeline(
        self,
        *,
        trace_id: UUID,
        question: str,
        route: QuestionRoute,
    ) -> DataPipelineOutput:
        started = perf_counter()
        semantic_retrieval = SemanticMetadataRetriever(self.db).retrieve(
            query=question,
            embedding_provider=self.embedding_provider,
            embedding_model=self.settings.embedding_model,
            embedding_version=self.settings.embedding_version,
            metadata_types=SEMANTIC_METADATA_TYPES,
        )
        self.trace_service.add_span(
            trace_id=trace_id,
            span_type="semantic_retrieval",
            input_json={
                "query": question,
                "metadata_types": SEMANTIC_METADATA_TYPES,
                **retrieval_trace_config(self.settings),
            },
            output_json={
                "item_count": len(semantic_retrieval.items),
                "source_counts": retrieval_source_counts(semantic_retrieval.items),
                "items": [semantic_hit_to_trace(hit) for hit in semantic_retrieval.items],
            },
            latency_ms=elapsed_ms(started),
            status="success",
        )

        sql_generation = await SQLGenerator(self.db, provider=self.provider, prompt_loader=self.prompt_loader).generate(
            question=question,
            semantic_hits=semantic_retrieval.items,
            normalized_time_range=route.extracted_entities.normalized_time_range,
        )
        self._add_llm_span(
            trace_id=trace_id,
            span_type="sql_generation",
            result=sql_generation.result,
            input_json={
                "question": question,
                "candidate_schema": sql_generation.candidate_schema,
            },
            output_json=sql_generation.result.parsed.model_dump(mode="json"),
        )

        guard_started = perf_counter()
        sql_guard = SQLGuard(
            allowed_schema=self.settings.sql_allowed_schema,
            default_limit=self.settings.sql_default_limit,
            max_limit=self.settings.sql_max_rows,
        ).validate(sql_generation.result.parsed.sql)
        self.trace_service.add_span(
            trace_id=trace_id,
            span_type="sql_guard",
            input_json={"sql": sql_generation.result.parsed.sql},
            output_json={
                "valid": sql_guard.valid,
                "validated_sql": sql_guard.validated_sql,
                "rewritten": sql_guard.rewritten,
                "violations": [violation.__dict__ for violation in sql_guard.violations],
            },
            latency_ms=elapsed_ms(guard_started),
            status="success" if sql_guard.valid else "failed",
        )
        if not sql_guard.valid:
            raise QAOrchestrationError("SQL Guard rejected generated SQL")

        sql_execution = self.sql_executor.execute(sql_guard)
        self.trace_service.add_span(
            trace_id=trace_id,
            span_type="sql_execution",
            input_json={"validated_sql": sql_guard.validated_sql},
            output_json={
                "columns": list(sql_execution.columns),
                "row_count": sql_execution.row_count,
                "result_preview": list(sql_execution.result_preview),
            },
            latency_ms=sql_execution.latency_ms,
            status="success",
        )

        explanation_result = await self._generate_sql_explanation(
            trace_id=trace_id,
            question=question,
            sql_guard=sql_guard,
            sql_execution=sql_execution,
        )
        chart_result = await self._generate_chart_spec(
            trace_id=trace_id,
            question=question,
            sql_execution=sql_execution,
        )
        return DataPipelineOutput(
            semantic_retrieval=semantic_retrieval,
            sql_generation=sql_generation,
            sql_guard=sql_guard,
            sql_execution=sql_execution,
            explanation_result=explanation_result,
            chart_result=chart_result,
        )

    async def _generate_sql_explanation(
        self,
        *,
        trace_id: UUID,
        question: str,
        sql_guard: SQLGuardResult,
        sql_execution: SQLExecutionResult,
    ) -> LLMJsonResult[SqlResultExplanation]:
        template = self.prompt_loader.load("sql_result_explanation")
        result = await self.provider.generate_json(
            purpose=template.purpose,
            prompt_name=template.prompt_name,
            prompt_version=template.prompt_version,
            system_prompt=SQL_RESULT_EXPLANATION_SYSTEM_PROMPT,
            user_prompt=template.render(
                question=question,
                validated_sql=sql_guard.validated_sql,
                columns=json_text(list(sql_execution.columns)),
                rows=json_text(list(sql_execution.result_preview)),
                row_count=sql_execution.row_count,
                data_sources=json_text(extract_data_sources(sql_execution.rows)),
            ),
            response_model=SqlResultExplanation,
            temperature=0.0,
        )
        self._add_llm_span(
            trace_id=trace_id,
            span_type="answer_generation",
            result=result,
            input_json={"question": question, "validated_sql": sql_guard.validated_sql},
            output_json=result.parsed.model_dump(mode="json"),
        )
        return result

    async def _generate_chart_spec(
        self,
        *,
        trace_id: UUID,
        question: str,
        sql_execution: SQLExecutionResult,
    ) -> LLMJsonResult[ChartSpec]:
        template = self.prompt_loader.load("chart_recommendation")
        result = await self.provider.generate_json(
            purpose=template.purpose,
            prompt_name=template.prompt_name,
            prompt_version=template.prompt_version,
            system_prompt=CHART_RECOMMENDATION_SYSTEM_PROMPT,
            user_prompt=template.render(
                question=question,
                columns=json_text(list(sql_execution.columns)),
                rows=json_text(list(sql_execution.result_preview)),
                field_types=json_text(infer_field_types(sql_execution.rows)),
            ),
            response_model=ChartSpec,
            temperature=0.0,
        )
        self._add_llm_span(
            trace_id=trace_id,
            span_type="chart_generation",
            result=result,
            input_json={"question": question, "columns": list(sql_execution.columns)},
            output_json=result.parsed.model_dump(mode="json"),
        )
        return result

    async def _generate_hybrid_answer(
        self,
        *,
        trace_id: UUID,
        question: str,
        policy: PolicyPipelineOutput,
        data: DataPipelineOutput,
    ) -> LLMJsonResult[HybridAnswer]:
        template = self.prompt_loader.load("hybrid_answer")
        result = await self.provider.generate_json(
            purpose=template.purpose,
            prompt_name=template.prompt_name,
            prompt_version=template.prompt_version,
            system_prompt=HYBRID_ANSWER_SYSTEM_PROMPT,
            user_prompt=template.render(
                question=question,
                policy_answer=policy.answer_result.parsed.answer,
                policy_citations=json_text(
                    [citation.model_dump(mode="json") for citation in policy.answer_result.parsed.citations]
                ),
                sql_explanation=data.explanation_result.parsed.summary,
                sql_result=json_text(
                    {
                        "validated_sql": data.sql_guard.validated_sql,
                        "row_count": data.sql_execution.row_count,
                        "result_preview": list(data.sql_execution.result_preview),
                    }
                ),
                chart_spec=json_text(data.chart_result.parsed.model_dump(mode="json")),
            ),
            response_model=HybridAnswer,
            temperature=0.0,
        )
        self._add_llm_span(
            trace_id=trace_id,
            span_type="answer_generation",
            result=result,
            input_json={"question": question, "mode": "hybrid"},
            output_json=result.parsed.model_dump(mode="json"),
        )
        return result

    def _policy_response(
        self,
        *,
        trace_id: UUID,
        request_id: str,
        route_type: RouteType,
        policy: PolicyPipelineOutput,
    ) -> QaResponse:
        answer = policy.answer_result.parsed
        return QaResponse(
            trace_id=trace_id,
            route_type=route_type,
            answer=answer_with_caveats(answer.answer, answer.caveat),
            citations=[
                QaCitation(
                    type="policy",
                    source_title=citation.source_title,
                    source_url=citation.source_url,
                    section_path=citation.section_path,
                    quote=citation.quote,
                )
                for citation in answer.citations
            ],
            sql=None,
            chart=None,
            request_id=request_id,
        )

    def _data_response(
        self,
        *,
        trace_id: UUID,
        request_id: str,
        route_type: RouteType,
        data: DataPipelineOutput,
    ) -> QaResponse:
        return QaResponse(
            trace_id=trace_id,
            route_type=route_type,
            answer=answer_with_caveats(
                data.explanation_result.parsed.summary,
                data.explanation_result.parsed.caveat,
            ),
            citations=[
                QaCitation(type="data", source_title=source.title, source_url=source.source_url)
                for source in data.explanation_result.parsed.data_sources
            ],
            sql=sql_payload(data),
            chart=data.chart_result.parsed,
            request_id=request_id,
        )

    def _hybrid_response(
        self,
        *,
        trace_id: UUID,
        request_id: str,
        route_type: RouteType,
        hybrid: LLMJsonResult[HybridAnswer],
        data: DataPipelineOutput,
    ) -> QaResponse:
        answer = hybrid.parsed
        return QaResponse(
            trace_id=trace_id,
            route_type=route_type,
            answer=answer_with_caveats(
                answer.answer,
                answer.caveat,
                data.explanation_result.parsed.caveat,
            ),
            citations=[
                QaCitation(
                    type="policy",
                    source_title=citation.source_title,
                    source_url=citation.source_url,
                    section_path=citation.section_path,
                    quote=citation.quote,
                )
                for citation in answer.policy_citations
            ]
            + [
                QaCitation(type="data", source_title=source.title, source_url=source.source_url)
                for source in answer.data_sources
            ],
            sql=sql_payload(data),
            chart=data.chart_result.parsed,
            request_id=request_id,
        )

    def _add_llm_span(
        self,
        *,
        trace_id: UUID,
        span_type: str,
        result: LLMJsonResult[BaseModel],
        input_json: dict,
        output_json: dict,
    ) -> None:
        self.trace_service.add_span(
            trace_id=trace_id,
            span_type=span_type,
            input_json=input_json,
            output_json=output_json,
            latency_ms=result.latency_ms,
            status=result.status,
            model_name=result.model_name,
            prompt_name=result.prompt_name,
            prompt_version=result.prompt_version,
            token_usage_json=result.token_usage_json,
            cost_json=result.cost_json,
            retry_count=result.retry_count,
        )


def sql_payload(data: DataPipelineOutput) -> QaSqlPayload:
    return QaSqlPayload(
        validated_sql=data.sql_guard.validated_sql or "",
        row_count=data.sql_execution.row_count,
        columns=list(data.sql_execution.columns),
        result_preview=list(data.sql_execution.result_preview),
    )


def elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def build_policy_retrieval_query(*, question: str, route: QuestionRoute) -> str:
    if route.route_type != "HYBRID_QA":
        return question
    topics = [" ".join(topic.split()) for topic in route.extracted_entities.policy_topics]
    expanded_topics: list[str] = []
    for topic in topics:
        if not topic:
            continue
        expanded_topics.append(topic)
        for source_topic, expansions in POLICY_TOPIC_EXPANSIONS.items():
            if source_topic in topic:
                expanded_topics.extend(expansions)
    focused_topics = list(dict.fromkeys(expanded_topics))
    return " ".join(focused_topics) or question


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def answer_with_caveats(answer: str, *caveats: str | None) -> str:
    normalized_caveats = list(
        dict.fromkeys(caveat.strip() for caveat in caveats if caveat and caveat.strip())
    )
    if not normalized_caveats:
        return answer
    return answer.rstrip() + "\n\n提示：" + "；".join(normalized_caveats)


def chunk_to_trace(chunk) -> dict:
    return {
        "chunk_id": str(chunk.chunk_id),
        "document_title": chunk.document_title,
        "heading_path": chunk.heading_path,
        "dense_score": chunk.dense_score,
        "keyword_score": chunk.keyword_score,
        "fulltext_score": chunk.fulltext_score,
        "exact_score": chunk.exact_score,
        "final_score": chunk.final_score,
        "match_sources": list(chunk.match_sources),
    }


def semantic_hit_to_trace(hit) -> dict:
    return {
        "metadata_id": str(hit.item.id),
        "metadata_type": hit.item.metadata_type,
        "name": hit.item.name,
        "related_table": hit.item.related_table,
        "related_field": hit.item.related_field,
        "dense_score": hit.dense_score,
        "keyword_score": hit.keyword_score,
        "fulltext_score": hit.fulltext_score,
        "exact_score": hit.exact_score,
        "final_score": hit.final_score,
        "match_sources": list(hit.match_sources),
    }


def retrieval_trace_config(settings: Settings) -> dict:
    return {
        "retrieval_strategy": ["dense_vector", "keyword", "fulltext", "rule_rerank"],
        "embedding_model": settings.embedding_model,
        "embedding_version": settings.embedding_version,
        "embedding_dim": settings.embedding_dim,
        "query_instruction_applied": bool(settings.embedding_query_instruction.strip()),
        "raw_query_vector_recorded": False,
    }


def retrieval_source_counts(items) -> dict[str, int]:
    counts = {"dense": 0, "keyword": 0, "fulltext": 0, "exact": 0}
    for item in items:
        for source in item.match_sources:
            if source in counts:
                counts[source] += 1
        if item.exact_score > 0:
            counts["exact"] += 1
    return counts


def extract_data_sources(rows) -> list[dict[str, str | None]]:
    sources: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for row in rows:
        title = row.get("source") or row.get("source_platform") or row.get("data_version")
        source_url = row.get("source_url")
        if title is None and source_url is None:
            continue
        key = (str(title or "结构化数据查询结果"), str(source_url) if source_url else None)
        if key in seen:
            continue
        seen.add(key)
        sources.append({"title": key[0], "source_url": key[1]})
    return sources or [{"title": "结构化数据查询结果", "source_url": None}]


def infer_field_types(rows) -> dict[str, str]:
    field_types: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            if key in field_types or value is None:
                continue
            if isinstance(value, bool):
                field_types[key] = "boolean"
            elif isinstance(value, int | float):
                field_types[key] = "number"
            else:
                field_types[key] = "text"
    return field_types
