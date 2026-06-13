from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Any

from aiohttp import web

from embedding_server.config import ServerSettings
from embedding_server.model import EmbeddingEngine, TransformersEmbeddingEngine

SETTINGS_KEY: web.AppKey[ServerSettings] = web.AppKey("settings", ServerSettings)
ENGINE_KEY: web.AppKey[EmbeddingEngine] = web.AppKey("engine", EmbeddingEngine)
LOGGER = logging.getLogger(__name__)


def json_error(*, status: int, code: str, message: str) -> web.Response:
    return web.json_response(
        {"error": {"code": code, "message": message}},
        status=status,
    )


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        LOGGER.exception("Unhandled embedding server error", extra={"path": request.path})
        return json_error(status=500, code="internal_error", message="embedding request failed")


def is_authorized(request: web.Request) -> bool:
    expected = request.app[SETTINGS_KEY].api_key
    if expected is None:
        return True
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return False
    return hmac.compare_digest(authorization[len(prefix) :], expected)


async def health(request: web.Request) -> web.Response:
    settings = request.app[SETTINGS_KEY]
    engine = request.app[ENGINE_KEY]
    return web.json_response(
        {
            "status": "ok",
            "ready": engine.loaded,
            "model": settings.model_name,
            "dimension": engine.dimension,
            "device": settings.device,
        }
    )


async def ready(request: web.Request) -> web.Response:
    if not request.app[ENGINE_KEY].loaded:
        return json_error(status=503, code="model_not_ready", message="model is not loaded")
    return web.json_response({"status": "ready"})


def validate_input(payload: Any, settings: ServerSettings) -> tuple[str, list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    model = payload.get("model")
    if model != settings.model_name:
        raise LookupError(f"unsupported model: {model}")
    if payload.get("encoding_format", "float") != "float":
        raise ValueError("only encoding_format=float is supported")

    raw_input = payload.get("input")
    texts = [raw_input] if isinstance(raw_input, str) else raw_input
    if not isinstance(texts, list) or not texts:
        raise ValueError("input must be a non-empty string or list of strings")
    if len(texts) > settings.max_batch_size:
        raise OverflowError(f"batch size exceeds {settings.max_batch_size}")
    if not all(isinstance(text, str) and text.strip() for text in texts):
        raise ValueError("all input items must be non-empty strings")
    if any(len(text) > settings.max_text_chars for text in texts):
        raise OverflowError(f"input text exceeds {settings.max_text_chars} characters")
    return model, texts


async def embeddings(request: web.Request) -> web.Response:
    if not is_authorized(request):
        return json_error(status=401, code="unauthorized", message="invalid API key")

    try:
        payload = await request.json()
    except Exception:
        return json_error(status=400, code="invalid_json", message="request body must be JSON")

    settings = request.app[SETTINGS_KEY]
    try:
        model, texts = validate_input(payload, settings)
    except LookupError as exc:
        return json_error(status=404, code="model_not_found", message=str(exc))
    except OverflowError as exc:
        return json_error(status=413, code="request_too_large", message=str(exc))
    except ValueError as exc:
        return json_error(status=400, code="invalid_request", message=str(exc))

    engine = request.app[ENGINE_KEY]
    if not engine.loaded:
        return json_error(status=503, code="model_not_ready", message="model is not loaded")

    vectors = await asyncio.to_thread(engine.encode, texts)
    if len(vectors) != len(texts) or any(len(vector) != settings.embedding_dim for vector in vectors):
        return json_error(
            status=500,
            code="invalid_model_output",
            message="model returned an unexpected vector shape",
        )
    return web.json_response(
        {
            "object": "list",
            "model": model,
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in enumerate(vectors)
            ],
        }
    )


def create_app(
    *,
    settings: ServerSettings | None = None,
    engine: EmbeddingEngine | None = None,
    load_model_on_startup: bool = True,
) -> web.Application:
    resolved_settings = settings or ServerSettings.from_env()
    resolved_engine = engine or TransformersEmbeddingEngine(resolved_settings)
    app = web.Application(middlewares=[error_middleware], client_max_size=2 * 1024 * 1024)
    app[SETTINGS_KEY] = resolved_settings
    app[ENGINE_KEY] = resolved_engine
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_post("/v1/embeddings", embeddings)

    if load_model_on_startup:
        async def load_model(_: web.Application) -> None:
            await asyncio.to_thread(resolved_engine.load)

        app.on_startup.append(load_model)
    return app
