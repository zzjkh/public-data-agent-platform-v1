from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.db.models.user import User
from app.ingestion.jobs import IngestionJobService, JobNotFoundError, JobStateError
from app.ingestion.schemas import JobCreateRequest, JobCreateResponse, JobListResponse, JobRead

router = APIRouter()


def build_service(db: Session, settings: Settings) -> IngestionJobService:
    return IngestionJobService(db, settings)


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    current_user: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobCreateResponse:
    job = build_service(db, settings).create_job(request=request, created_by=current_user.id)
    return JobCreateResponse(job_id=job.id, status=job.status, request_id=request_id)


@router.get("", response_model=JobListResponse)
def list_jobs(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    job_type: str | None = None,
    target_type: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobListResponse:
    items, total = build_service(db, settings).list_jobs(
        page=page,
        page_size=page_size,
        status=status_filter,
        job_type=job_type,
        target_type=target_type,
    )
    return JobListResponse(
        items=[JobRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobRead:
    try:
        job = build_service(db, settings).get_job(job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    response = JobRead.model_validate(job)
    response.request_id = request_id
    return response


@router.post("/{job_id}/retry", response_model=JobRead)
def retry_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobRead:
    try:
        job = build_service(db, settings).retry_job(job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except JobStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    response = JobRead.model_validate(job)
    response.request_id = request_id
    return response


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobRead:
    try:
        job = build_service(db, settings).cancel_job(job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except JobStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    response = JobRead.model_validate(job)
    response.request_id = request_id
    return response
