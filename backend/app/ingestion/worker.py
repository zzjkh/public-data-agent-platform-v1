from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import bind_log_context, get_logger
from app.db.models.ingestion_job import IngestionJob
from app.db.repositories.ingestion_job import IngestionJobRepository

JobHandler = Callable[[Session, IngestionJob], dict | None]


def run_worker_once(
    *,
    db: Session,
    settings: Settings,
    handlers: dict[str, JobHandler],
) -> IngestionJob | None:
    repository = IngestionJobRepository(db)
    repository.recover_stuck_jobs(timeout_seconds=settings.job_heartbeat_timeout_seconds)
    job = repository.acquire_next_job(worker_id=settings.worker_id)
    if job is None:
        db.commit()
        return None

    bind_log_context(job_id=str(job.id), job_type=job.job_type, status=job.status)
    logger = get_logger()
    logger.info("job_started")
    handler = handlers.get(job.job_type)
    try:
        if handler is None:
            raise RuntimeError(f"No handler registered for job_type={job.job_type}")
        result = handler(db, job)
        repository.mark_success(job=job, result_json=result or {})
        db.commit()
        logger.info("job_succeeded", status=job.status)
    except Exception as exc:
        if not db.is_active:
            db.rollback()
        failed_job = repository.get_by_id(job.id)
        if failed_job is not None:
            repository.mark_failed(job=failed_job, error_message=str(exc))
        db.commit()
        logger.exception("job_failed", status=failed_job.status if failed_job is not None else "failed")
    return job
