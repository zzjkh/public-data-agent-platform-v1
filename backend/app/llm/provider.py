from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.logging import get_logger


T = TypeVar("T", bound=BaseModel)
RAW_TEXT_PREVIEW_LIMIT = 1000


class LLMProviderError(RuntimeError):
    pass


class LLMProviderPromptError(LLMProviderError):
    pass


class LLMProviderAuthError(LLMProviderError):
    pass


class LLMProviderBadRequestError(LLMProviderError):
    pass


class LLMProviderRetryableError(LLMProviderError):
    pass


class LLMProviderValidationError(LLMProviderError):
    pass


@dataclass(frozen=True)
class LLMJsonResult(Generic[T]):
    parsed: T
    raw_text_preview: str
    token_usage_json: dict
    cost_json: dict
    latency_ms: int
    retry_count: int
    model_name: str
    prompt_name: str
    prompt_version: str
    purpose: str
    status: str = "success"


class DeepSeekLLMProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.model_name = settings.deepseek_model
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None
        self.logger = get_logger()

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
        ensure_json_prompt(system_prompt=system_prompt, user_prompt=user_prompt)
        retry_limit = self.settings.llm_max_retries if max_retries is None else max_retries
        if retry_limit < 0:
            raise LLMProviderPromptError("max_retries must not be negative")

        started = time.perf_counter()
        last_error: Exception | None = None
        raw_text_preview = ""
        usage: dict = {}
        retry_count = 0
        validation_feedback: str | None = None

        for attempt in range(retry_limit + 1):
            if attempt > 0:
                retry_count += 1
            try:
                payload = await self._post_chat_completion(
                    purpose=purpose,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    validation_feedback=validation_feedback,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds or self.settings.llm_request_timeout_seconds,
                    max_tokens=max_tokens or self.settings.llm_max_tokens,
                )
                raw_text = extract_message_content(payload)
                raw_text_preview = preview(raw_text)
                usage = dict(payload.get("usage") or {})
                parsed = response_model.model_validate_json(raw_text)
                latency_ms = elapsed_ms(started)
                self.logger.info(
                    "llm_generate_json_success",
                    purpose=purpose,
                    prompt_name=prompt_name,
                    prompt_version=prompt_version,
                    model_name=self.model_name,
                    thinking_mode=self.settings.llm_thinking_mode,
                    latency_ms=latency_ms,
                    retry_count=retry_count,
                )
                return LLMJsonResult(
                    parsed=parsed,
                    raw_text_preview=raw_text_preview,
                    token_usage_json=usage,
                    cost_json=estimate_cost_json(usage),
                    latency_ms=latency_ms,
                    retry_count=retry_count,
                    model_name=self.model_name,
                    prompt_name=prompt_name,
                    prompt_version=prompt_version,
                    purpose=purpose,
                )
            except (ValidationError, ValueError) as exc:
                last_error = exc
                validation_feedback = validation_retry_feedback(exc, raw_text_preview)
                if attempt >= retry_limit:
                    break
            except LLMProviderRetryableError as exc:
                last_error = exc
                if attempt >= retry_limit:
                    break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= retry_limit:
                    break

        latency_ms = elapsed_ms(started)
        self.logger.warning(
            "llm_generate_json_failed",
            purpose=purpose,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            model_name=self.model_name,
            thinking_mode=self.settings.llm_thinking_mode,
            latency_ms=latency_ms,
            retry_count=retry_count,
            error=str(last_error),
        )
        if isinstance(last_error, LLMProviderRetryableError):
            raise LLMProviderRetryableError(
                f"LLM provider retryable failure after {retry_count + 1} attempts: {last_error}"
            ) from last_error
        if isinstance(last_error, (httpx.TimeoutException, httpx.TransportError)):
            raise LLMProviderRetryableError(
                f"LLM provider transport failure after {retry_count + 1} attempts: {last_error}"
            ) from last_error
        raise LLMProviderValidationError(
            f"LLM JSON generation failed after {retry_count + 1} attempts: {last_error}"
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def _post_chat_completion(
        self,
        *,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        validation_feedback: str | None,
        temperature: float,
        timeout_seconds: int,
        max_tokens: int,
    ) -> dict:
        client = self._client or httpx.AsyncClient()
        if self._client is None:
            self._client = client

        response = await client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "messages": build_messages(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    validation_feedback=validation_feedback,
                ),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "thinking": {"type": self.settings.llm_thinking_mode},
            },
            timeout=timeout_seconds,
        )
        map_provider_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise LLMProviderRetryableError("Provider returned non-JSON HTTP payload") from exc


def build_messages(
    *,
    system_prompt: str,
    user_prompt: str,
    validation_feedback: str | None,
) -> list[dict[str, str]]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if validation_feedback:
        messages.append(
            {
                "role": "user",
                "content": validation_feedback,
            }
        )
    return messages


def ensure_json_prompt(*, system_prompt: str, user_prompt: str) -> None:
    combined = f"{system_prompt}\n{user_prompt}".lower()
    if "json" not in combined:
        raise LLMProviderPromptError("DeepSeek JSON Output requires prompt text to mention JSON.")


def extract_message_content(payload: dict) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderRetryableError("Provider response does not contain choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMProviderRetryableError("Provider response content is empty")
    return content.strip()


def map_provider_status(response: httpx.Response) -> None:
    status_code = response.status_code
    if status_code < 400:
        return
    if status_code in {401, 403}:
        raise LLMProviderAuthError(f"Provider auth failed with status {status_code}")
    if status_code == 400:
        raise LLMProviderBadRequestError(f"Provider bad request: {preview(response.text)}")
    if status_code == 429 or status_code >= 500:
        raise LLMProviderRetryableError(f"Provider retryable status {status_code}: {preview(response.text)}")
    raise LLMProviderBadRequestError(f"Provider request failed with status {status_code}: {preview(response.text)}")


def validation_retry_feedback(exc: Exception, raw_text_preview: str) -> str:
    return (
        "上一次输出没有通过 JSON/Pydantic 校验。"
        "请只输出一个合法 JSON object，不要使用 Markdown 代码块。"
        f"校验错误：{exc}\n"
        f"上一次输出预览：{raw_text_preview}"
    )


def estimate_cost_json(usage: dict) -> dict:
    return {
        "currency": "CNY",
        "estimated": None,
        "reason": "pricing_not_configured",
        "usage": usage,
    }


def preview(text: str, *, limit: int = RAW_TEXT_PREVIEW_LIMIT) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "...[truncated]"


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
