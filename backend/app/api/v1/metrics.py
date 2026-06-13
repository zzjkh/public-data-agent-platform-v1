from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.datasets.metrics_service import MetricImportRequestError, MetricNotFoundError, MetricService
from app.datasets.schemas import (
    MetricImportRequest,
    MetricListResponse,
    MetricRead,
    MetricValueListResponse,
    MetricValueRead,
)
from app.db.models.user import User
from app.ingestion.schemas import JobCreateResponse

router = APIRouter()


def build_service(db: Session, settings: Settings) -> MetricService:
    return MetricService(db, settings)


@router.post("/import", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
def import_metrics(
    request: MetricImportRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    current_user: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobCreateResponse:
    try:
        job = build_service(db, settings).create_import_job(
            request=request,
            created_by=current_user.id,
        )
    except MetricImportRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JobCreateResponse(job_id=job.id, status=job.status, request_id=request_id)


@router.get("", response_model=MetricListResponse)
def list_metrics(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: str | None = None,
    domain: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> MetricListResponse:
    items, total = build_service(db, settings).list_metrics(
        page=page,
        page_size=page_size,
        keyword=keyword,
        domain=domain,
    )
    return MetricListResponse(
        items=[MetricRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.get("/{metric_id}/values", response_model=MetricValueListResponse)
def list_metric_values(
    metric_id: UUID,
    region_name: str | None = None,
    stat_year_from: int | None = None,
    stat_year_to: int | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> MetricValueListResponse:
    service = build_service(db, settings)
    try:
        metric = service.get_metric(metric_id=metric_id)
    except MetricNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    values = service.list_values(
        metric_id=metric.id,
        region_name=region_name,
        stat_year_from=stat_year_from,
        stat_year_to=stat_year_to,
    )
    return MetricValueListResponse(
        metric=MetricRead.model_validate(metric),
        items=[MetricValueRead.model_validate(value) for value in values],
        total=len(values),
        request_id=request_id,
    )
