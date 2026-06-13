from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.ingestion_job import IngestionJob
from app.db.repositories.ingestion_job import IngestionJobRepository
from app.ingestion.schemas import JobCreateRequest


class JobNotFoundError(ValueError):
    pass


class JobStateError(ValueError):
    pass


class IngestionJobService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.repository = IngestionJobRepository(db)

    def create_job(self, *, request: JobCreateRequest, created_by: UUID | None) -> IngestionJob:
        job = self.repository.create(
            job_type=request.job_type,
            target_type=request.target_type,
            target_id=request.target_id,
            payload_json=request.payload,
            priority=request.priority,
            max_retries=request.max_retries
            if request.max_retries is not None
            else self.settings.job_max_retries,
            created_by=created_by,
        )
        self.db.commit()
        self.db.refresh(job)
        return job

    def list_jobs(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        job_type: str | None,
        target_type: str | None,
    ) -> tuple[list[IngestionJob], int]:
        return self.repository.list(
            page=page,
            page_size=page_size,
            status=status,
            job_type=job_type,
            target_type=target_type,
        )

    def get_job(self, *, job_id: UUID) -> IngestionJob:
        job = self.repository.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError("Job not found")
        return job

    def retry_job(self, *, job_id: UUID) -> IngestionJob:
        job = self.get_job(job_id=job_id)
        if job.status != "failed":
            raise JobStateError("Only failed jobs can be retried in V1")
        job = self.repository.retry(job=job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def cancel_job(self, *, job_id: UUID) -> IngestionJob:
        job = self.get_job(job_id=job_id)
        if job.status != "pending":
            raise JobStateError("Only pending jobs can be cancelled in V1")
        job = self.repository.cancel_pending(job=job)
        self.db.commit()
        self.db.refresh(job)
        return job
