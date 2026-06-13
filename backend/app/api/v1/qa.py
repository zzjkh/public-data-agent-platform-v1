from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_current_user, get_db, get_request_id
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models.user import User
from app.ingestion.handlers import build_embedding_provider
from app.llm.embedding_provider import EmbeddingProviderError
from app.llm.provider import DeepSeekLLMProvider, LLMProviderError
from app.qa.orchestrator import QAOrchestrationError, QAOrchestrator
from app.qa.schemas import QaAskRequest, QaResponse

router = APIRouter()
logger = get_logger()


def build_orchestrator(
    *,
    db: Session,
    settings: Settings,
    provider: DeepSeekLLMProvider,
) -> QAOrchestrator:
    embedding_provider = build_embedding_provider(
        settings,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
    )
    return QAOrchestrator(
        db,
        settings=settings,
        provider=provider,
        embedding_provider=embedding_provider,
    )


@router.post("/ask", response_model=QaResponse)
async def ask_question(
    request: QaAskRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    current_user: User = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> QaResponse:
    provider = DeepSeekLLMProvider(settings)
    try:
        orchestrator = build_orchestrator(db=db, settings=settings, provider=provider)
        return await orchestrator.ask(
            question=request.question,
            user_id=current_user.id,
            request_id=request_id,
        )
    except QAOrchestrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EmbeddingProviderError as exc:
        logger.warning(
            "qa_dependency_unavailable",
            dependency="embedding",
            error_type=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding 服务暂不可用，请稍后重试。",
        ) from exc
    except LLMProviderError as exc:
        logger.warning(
            "qa_dependency_unavailable",
            dependency="llm",
            error_type=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="大模型服务暂不可用，请稍后重试。",
        ) from exc
    finally:
        await provider.aclose()
