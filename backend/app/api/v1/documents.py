from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.db.models.user import User
from app.documents.schemas import (
    DocumentElementListResponse,
    DocumentElementRead,
    DocumentVersionPublishRequest,
    DocumentVersionPublishResponse,
    RagChunkListResponse,
    RagChunkRead,
)
from app.documents.service import DocumentParseError, DocumentPublishError, DocumentService
from app.files.storage import LocalFileStorage

router = APIRouter()


@router.post("/{version_id}/publish", response_model=DocumentVersionPublishResponse)
def publish_document_version(
    version_id: UUID,
    request: DocumentVersionPublishRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> DocumentVersionPublishResponse:
    service = DocumentService(db, LocalFileStorage(settings.file_storage_root))
    try:
        version, archived_version_ids = service.publish_version(
            version_id=version_id,
            embedding_model=settings.embedding_model,
            embedding_version=settings.embedding_version,
            metadata=request.model_dump(),
        )
    except DocumentPublishError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if version.published_at is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Publish time missing")
    return DocumentVersionPublishResponse(
        document_id=version.document_id,
        version_id=version.id,
        publish_status=version.publish_status,
        published_at=version.published_at,
        archived_version_ids=archived_version_ids,
        request_id=request_id,
    )


@router.get("/{version_id}/elements", response_model=DocumentElementListResponse)
def list_document_elements(
    version_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> DocumentElementListResponse:
    service = DocumentService(db, LocalFileStorage(settings.file_storage_root))
    try:
        all_items = service.list_elements(version_id=version_id)
    except DocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    start = (page - 1) * page_size
    end = start + page_size
    return DocumentElementListResponse(
        items=[DocumentElementRead.model_validate(item) for item in all_items[start:end]],
        page=page,
        page_size=page_size,
        total=len(all_items),
        request_id=request_id,
    )


@router.get("/{version_id}/chunks", response_model=RagChunkListResponse)
def list_rag_chunks(
    version_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> RagChunkListResponse:
    service = DocumentService(db, LocalFileStorage(settings.file_storage_root))
    try:
        all_items = service.list_chunks(version_id=version_id)
    except DocumentParseError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    start = (page - 1) * page_size
    end = start + page_size
    return RagChunkListResponse(
        items=[RagChunkRead.model_validate(item) for item in all_items[start:end]],
        page=page,
        page_size=page_size,
        total=len(all_items),
        request_id=request_id,
    )
