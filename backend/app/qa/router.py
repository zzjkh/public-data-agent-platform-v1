from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from typing import Protocol

from app.llm.contracts import NormalizedTimeRange, QuestionRoute
from app.llm.prompts import PromptLoader
from app.llm.provider import LLMJsonResult


ROUTER_SYSTEM_PROMPT = """你是公共数据开放智能知识与数据分析平台中的问题路由模块。
你必须严格遵守当前任务的输入边界。
你只能判断用户问题应走哪条处理链路，不要直接回答用户问题。
输出必须是合法 JSON object，不要使用 Markdown 代码块。"""

AVAILABLE_CAPABILITIES = """- POLICY_QA：回答公共数据开放政策、授权运营、登记管理、数据安全等政策文本问题。
- DATA_QA：查询北京 GDP、常住人口、开放数据目录统计等结构化数据。
- HYBRID_QA：同时需要政策依据和结构化数据分析的问题。
- OTHER：超出范围、资料不足、要求执行危险操作或无法判断的问题。"""

CHINESE_NUMERALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class QuestionRouterProvider(Protocol):
    async def generate_json(
        self,
        *,
        purpose: str,
        prompt_name: str,
        prompt_version: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[QuestionRoute],
        temperature: float = 0.1,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
    ) -> LLMJsonResult[QuestionRoute]:
        raise NotImplementedError


class QuestionRouter:
    def __init__(
        self,
        *,
        provider: QuestionRouterProvider,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.provider = provider
        self.prompt_loader = prompt_loader or PromptLoader()

    async def route(
        self,
        *,
        question: str,
        current_date: date | None = None,
    ) -> LLMJsonResult[QuestionRoute]:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question must not be empty")

        current_date = current_date or date.today()
        template = self.prompt_loader.load("router")
        user_prompt = template.render(
            question=normalized_question,
            available_capabilities=AVAILABLE_CAPABILITIES,
            current_date=current_date.isoformat(),
        )
        result = await self.provider.generate_json(
            purpose=template.purpose,
            prompt_name=template.prompt_name,
            prompt_version=template.prompt_version,
            system_prompt=ROUTER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=QuestionRoute,
            temperature=0.0,
        )
        route = enrich_question_route(
            route=result.parsed,
            question=normalized_question,
            current_date=current_date,
        )
        if route == result.parsed:
            return result
        return replace(result, parsed=route)


def enrich_question_route(
    *,
    route: QuestionRoute,
    question: str,
    current_date: date,
) -> QuestionRoute:
    extracted = route.extracted_entities
    inferred_time_range = infer_normalized_time_range(question=question, current_date=current_date)
    if inferred_time_range is None:
        return route

    return route.model_copy(
        update={
            "extracted_entities": extracted.model_copy(
                update={
                    "time_range": extracted.time_range or inferred_time_range.source_text,
                    "normalized_time_range": inferred_time_range,
                }
            )
        }
    )


def infer_normalized_time_range(
    *,
    question: str,
    current_date: date,
) -> NormalizedTimeRange | None:
    year_range = infer_explicit_year_range(question)
    if year_range is not None:
        start_year, end_year, source_text = year_range
        return NormalizedTimeRange(
            start_year=start_year,
            end_year=end_year,
            grain="year",
            source_text=source_text,
            confidence=0.95,
        )

    recent_years = infer_recent_year_count(question)
    if recent_years is not None:
        year_count, source_text = recent_years
        end_year = current_date.year
        return NormalizedTimeRange(
            start_year=end_year - year_count + 1,
            end_year=end_year,
            grain="year",
            source_text=source_text,
            confidence=0.85,
        )

    if "去年" in question:
        year = current_date.year - 1
        return NormalizedTimeRange(
            start_year=year,
            end_year=year,
            grain="year",
            source_text="去年",
            confidence=0.9,
        )
    if "今年" in question:
        year = current_date.year
        return NormalizedTimeRange(
            start_year=year,
            end_year=year,
            grain="year",
            source_text="今年",
            confidence=0.9,
        )

    single_year = infer_single_year(question)
    if single_year is not None:
        return NormalizedTimeRange(
            start_year=single_year,
            end_year=single_year,
            grain="year",
            source_text=f"{single_year}年",
            confidence=0.9,
        )
    return None


def infer_explicit_year_range(question: str) -> tuple[int, int, str] | None:
    match = re.search(r"(20\d{2})\s*年?\s*(?:到|至|~|-|—)\s*(20\d{2})\s*年?", question)
    if match is None:
        return None
    start_year = int(match.group(1))
    end_year = int(match.group(2))
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    return start_year, end_year, match.group(0)


def infer_recent_year_count(question: str) -> tuple[int, str] | None:
    match = re.search(r"(?:近|最近)(\d{1,2})年", question)
    if match is not None:
        return int(match.group(1)), match.group(0)

    match = re.search(r"(?:近|最近)([一二两三四五六七八九十])年", question)
    if match is not None:
        return CHINESE_NUMERALS[match.group(1)], match.group(0)

    if "最近一年" in question:
        return 1, "最近一年"
    if "近一年" in question:
        return 1, "近一年"
    return None


def infer_single_year(question: str) -> int | None:
    match = re.search(r"(20\d{2})\s*年", question)
    if match is None:
        return None
    return int(match.group(1))
