from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.datasets.schemas import (
    DatasetImportRequest,
    OpenDatasetDetailResponse,
    OpenDatasetFieldRead,
    OpenDatasetListResponse,
    OpenDatasetRead,
)
from app.datasets.service import DatasetImportRequestError, DatasetNotFoundError, OpenDatasetService
from app.db.models.user import User
from app.ingestion.schemas import JobCreateResponse

router = APIRouter()


def build_service(db: Session, settings: Settings) -> OpenDatasetService:
    return OpenDatasetService(db, settings)


@router.post("/import", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
def import_datasets(
    request: DatasetImportRequest,
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
    except DatasetImportRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JobCreateResponse(job_id=job.id, status=job.status, request_id=request_id)


@router.get("", response_model=OpenDatasetListResponse)
def list_datasets(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: str | None = None,
    category: str | None = None,
    department: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> OpenDatasetListResponse:
    items, total = build_service(db, settings).list_datasets(
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        department=department,
        status=status_filter,
    )
    return OpenDatasetListResponse(
        items=[OpenDatasetRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.get("/{dataset_id}", response_model=OpenDatasetDetailResponse)
def get_dataset(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> OpenDatasetDetailResponse:
    service = build_service(db, settings)
    try:
        dataset = service.get_dataset(dataset_id=dataset_id)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    fields = service.list_fields(dataset_id=dataset.id)
    payload = OpenDatasetRead.model_validate(dataset).model_dump()
    return OpenDatasetDetailResponse(
        **payload,
        fields=[OpenDatasetFieldRead.model_validate(field) for field in fields],
        request_id=request_id,
    )
