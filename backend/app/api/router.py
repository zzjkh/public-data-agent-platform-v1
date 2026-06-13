from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.v1.auth import router as auth_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.documents import router as document_versions_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.files import router as files_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.qa import router as qa_router
from app.api.v1.semantic import router as semantic_router
from app.api.v1.traces import router as traces_router

router = APIRouter()
router.include_router(auth_router, prefix="/api/auth", tags=["auth"])
router.include_router(
    document_versions_router,
    prefix="/api/document-versions",
    tags=["document-versions"],
)
router.include_router(files_router, prefix="/api/files", tags=["files"])
router.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
router.include_router(datasets_router, prefix="/api/datasets", tags=["datasets"])
router.include_router(metrics_router, prefix="/api/metrics", tags=["metrics"])
router.include_router(semantic_router, prefix="/api/semantic", tags=["semantic"])
router.include_router(qa_router, prefix="/api/qa", tags=["qa"])
router.include_router(traces_router, prefix="/api/traces", tags=["traces"])
router.include_router(evaluation_router, prefix="/api/eval", tags=["evaluation"])


@router.get("/health", tags=["system"])
def health(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.app_env,
    }
