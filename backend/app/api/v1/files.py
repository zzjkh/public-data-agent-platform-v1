from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.db.models.user import User
from app.files.schemas import SourceFileListResponse, SourceFileRead, SourceFileUploadResponse
from app.files.service import SourceFileService
from app.files.storage import EmptyUploadError, LocalFileStorage, UnsupportedFileTypeError

router = APIRouter()


@router.post("/upload", response_model=SourceFileUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: Annotated[UploadFile, File()],
    source_url: Annotated[str | None, Form()] = None,
    file_version: Annotated[str, Form(min_length=1, max_length=64)] = "v1",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    current_user: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> SourceFileUploadResponse:
    service = SourceFileService(db, LocalFileStorage(settings.file_storage_root))
    try:
        source_file = service.upload(
            upload_file=file,
            source_url=source_url,
            file_version=file_version,
            uploaded_by=current_user.id,
        )
    except (UnsupportedFileTypeError, EmptyUploadError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SourceFileUploadResponse(
        file_id=source_file.id,
        storage_uri=source_file.storage_uri,
        file_hash=source_file.file_hash,
        parse_status=source_file.parse_status,
        request_id=request_id,
    )


@router.get("", response_model=SourceFileListResponse)
def list_files(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    parse_status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> SourceFileListResponse:
    service = SourceFileService(db, LocalFileStorage(settings.file_storage_root))
    items, total = service.list(
        page=page,
        page_size=page_size,
        parse_status=parse_status,
        keyword=keyword,
    )
    return SourceFileListResponse(
        items=[SourceFileRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )
