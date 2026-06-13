from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_db, get_request_id, require_admin_user
from app.core.config import Settings
from app.db.models.user import User
from app.ingestion.handlers import build_embedding_provider
from app.ingestion.schemas import JobCreateResponse
from app.semantic.retriever import SemanticMetadataRetriever, SemanticRetrievalError
from app.semantic.schemas import (
    SemanticMetadataItemRead,
    SemanticMetadataListResponse,
    SemanticMetadataRebuildRequest,
    SemanticMetadataSearchHit,
    SemanticMetadataSearchRequest,
    SemanticMetadataSearchResponse,
)
from app.semantic.service import SemanticMetadataError, SemanticMetadataService

router = APIRouter()


def build_service(db: Session, settings: Settings) -> SemanticMetadataService:
    return SemanticMetadataService(db, settings)


@router.post("/rebuild", response_model=JobCreateResponse, status_code=status.HTTP_201_CREATED)
def rebuild_semantic_metadata(
    request: SemanticMetadataRebuildRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    current_user: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> JobCreateResponse:
    try:
        job = build_service(db, settings).create_rebuild_job(
            request=request,
            created_by=current_user.id,
        )
    except SemanticMetadataError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JobCreateResponse(job_id=job.id, status=job.status, request_id=request_id)


@router.get("/items", response_model=SemanticMetadataListResponse)
def list_semantic_metadata_items(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    metadata_type: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> SemanticMetadataListResponse:
    try:
        items, total = build_service(db, settings).list_items(
            page=page,
            page_size=page_size,
            metadata_type=metadata_type,
            keyword=keyword,
        )
    except SemanticMetadataError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SemanticMetadataListResponse(
        items=[SemanticMetadataItemRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.post("/search", response_model=SemanticMetadataSearchResponse)
def search_semantic_metadata(
    request: SemanticMetadataSearchRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    _: User = Depends(require_admin_user),
    request_id: str = Depends(get_request_id),
) -> SemanticMetadataSearchResponse:
    provider = build_embedding_provider(
        settings,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
    )
    try:
        result = SemanticMetadataRetriever(db).retrieve(
            query=request.query,
            embedding_provider=provider,
            embedding_model=settings.embedding_model,
            embedding_version=settings.embedding_version,
            metadata_types=request.metadata_types,
            top_k=request.top_k,
        )
    except SemanticRetrievalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return SemanticMetadataSearchResponse(
        query=result.query,
        items=[
            SemanticMetadataSearchHit(
                item=SemanticMetadataItemRead.model_validate(hit.item),
                score=hit.final_score,
                dense_score=hit.dense_score,
                keyword_score=hit.keyword_score,
                fulltext_score=hit.fulltext_score,
                exact_score=hit.exact_score,
                match_sources=hit.match_sources,
            )
            for hit in result.items
        ],
        request_id=request_id,
    )
