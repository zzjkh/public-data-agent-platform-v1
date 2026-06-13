from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_request_id
from app.db.models.user import User
from app.trace.schemas import TraceDetailResponse, TraceListResponse, TraceRead, TraceSpanRead
from app.trace.service import TraceNotFoundError, TraceService

router = APIRouter()


def can_view_all_traces(user: User) -> bool:
    return user.role == "admin"


@router.get("", response_model=TraceListResponse)
def list_traces(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    route_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> TraceListResponse:
    items, total = TraceService(db).list_traces(
        page=page,
        page_size=page_size,
        user_id=current_user.id,
        include_all=can_view_all_traces(current_user),
        status=status_filter,
        route_type=route_type,
    )
    return TraceListResponse(
        items=[TraceRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        request_id=request_id,
    )


@router.get("/{trace_id}", response_model=TraceDetailResponse)
def get_trace(
    trace_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> TraceDetailResponse:
    try:
        trace, spans = TraceService(db).get_trace_with_spans(
            trace_id=trace_id,
            user_id=current_user.id,
            include_all=can_view_all_traces(current_user),
        )
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    payload = TraceRead.model_validate(trace).model_dump()
    return TraceDetailResponse(
        **payload,
        spans=[TraceSpanRead.model_validate(span) for span in spans],
        request_id=request_id,
    )
