from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.db.models.user import User
from app.evaluation.schemas import (
    EvalCaseCreateRequest,
    EvalCaseListResponse,
    EvalCaseRead,
    EvalRunCreateRequest,
    EvalRunDetailResponse,
    EvalRunListResponse,
    EvalRunRead,
    EvalResultRead,
)
from app.evaluation.service import EvaluationError, EvaluationService
from app.ingestion.handlers import build_embedding_provider
from app.llm.provider import DeepSeekLLMProvider
from app.qa.orchestrator import QAOrchestrator

router = APIRouter()


def build_eval_runner(
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


@router.post("/cases", response_model=EvalCaseRead, status_code=status.HTTP_201_CREATED)
def create_case(
    request: EvalCaseCreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
) -> EvalCaseRead:
    case, _ = EvaluationService(db, settings).upsert_case(request)
    db.commit()
    return EvalCaseRead.model_validate(case)


@router.get("/cases", response_model=EvalCaseListResponse)
def list_cases(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    case_type: str | None = None,
    enabled: bool | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> EvalCaseListResponse:
    items, total = EvaluationService(db, settings).list_cases(
        page=page,
        page_size=page_size,
        case_type=case_type,
        enabled=enabled,
    )
    return EvalCaseListResponse(
        items=[EvalCaseRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.post("/runs", response_model=EvalRunDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    request: EvalRunCreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    current_user: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> EvalRunDetailResponse:
    provider = DeepSeekLLMProvider(settings)
    try:
        runner = build_eval_runner(db=db, settings=settings, provider=provider)
        run, results = await EvaluationService(db, settings).create_and_run(
            request=request,
            runner=runner,
            user_id=current_user.id,
            request_id=request_id,
        )
    except EvaluationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await provider.aclose()

    payload = EvalRunRead.model_validate(run).model_dump()
    return EvalRunDetailResponse(
        **payload,
        results=[EvalResultRead.model_validate(result) for result in results],
        request_id=request_id,
    )


@router.get("/runs", response_model=EvalRunListResponse)
def list_runs(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> EvalRunListResponse:
    items, total = EvaluationService(db, settings).list_runs(
        page=page,
        page_size=page_size,
        status=status_filter,
    )
    return EvalRunListResponse(
        items=[EvalRunRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.get("/runs/{run_id}", response_model=EvalRunDetailResponse)
def get_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> EvalRunDetailResponse:
    try:
        run, results = EvaluationService(db, settings).get_run_with_results(run_id)
    except EvaluationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    payload = EvalRunRead.model_validate(run).model_dump()
    return EvalRunDetailResponse(
        **payload,
        results=[EvalResultRead.model_validate(result) for result in results],
        request_id=request_id,
    )
