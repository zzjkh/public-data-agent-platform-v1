from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.ingestion_job import IngestionJob


TERMINAL_JOB_STATUSES = {"success", "partial", "failed", "cancelled"}


class IngestionJobRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        job_type: str,
        target_type: str,
        target_id: UUID | None,
        payload_json: dict,
        priority: int,
        max_retries: int,
        created_by: UUID | None,
    ) -> IngestionJob:
        job = IngestionJob(
            job_type=job_type,
            target_type=target_type,
            target_id=target_id,
            payload_json=payload_json,
            priority=priority,
            max_retries=max_retries,
            created_by=created_by,
        )
        self.db.add(job)
        self.db.flush()
        return job

    def get_by_id(self, job_id: UUID) -> IngestionJob | None:
        return self.db.get(IngestionJob, job_id)

    def list(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        job_type: str | None = None,
        target_type: str | None = None,
    ) -> tuple[list[IngestionJob], int]:
        statement = select(IngestionJob)
        count_statement = select(func.count(IngestionJob.id))

        if status:
            statement = statement.where(IngestionJob.status == status)
            count_statement = count_statement.where(IngestionJob.status == status)
        if job_type:
            statement = statement.where(IngestionJob.job_type == job_type)
            count_statement = count_statement.where(IngestionJob.job_type == job_type)
        if target_type:
            statement = statement.where(IngestionJob.target_type == target_type)
            count_statement = count_statement.where(IngestionJob.target_type == target_type)

        total = self.db.scalar(count_statement) or 0
        items = list(
            self.db.scalars(
                statement.order_by(IngestionJob.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def acquire_next_job(self, *, worker_id: str) -> IngestionJob | None:
        now = datetime.now(UTC)
        statement = (
            select(IngestionJob)
            .where(IngestionJob.status == "pending")
            .order_by(IngestionJob.priority.asc(), IngestionJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = self.db.scalar(statement)
        if job is None:
            return None

        job.status = "running"
        job.locked_by = worker_id
        job.locked_at = now
        job.heartbeat_at = now
        job.started_at = job.started_at or now
        self.db.flush()
        return job

    def heartbeat(self, *, job: IngestionJob, progress_percent: int | None = None) -> IngestionJob:
        job.heartbeat_at = datetime.now(UTC)
        if progress_percent is not None:
            job.progress_percent = progress_percent
        self.db.flush()
        return job

    def mark_success(self, *, job: IngestionJob, result_json: dict | None = None) -> IngestionJob:
        job.status = "success"
        job.progress_percent = 100
        job.result_json = result_json or {}
        job.error_message = None
        job.finished_at = datetime.now(UTC)
        job.locked_by = None
        job.locked_at = None
        self.db.flush()
        return job

    def mark_failed(self, *, job: IngestionJob, error_message: str) -> IngestionJob:
        now = datetime.now(UTC)
        job.error_message = error_message
        job.locked_by = None
        job.locked_at = None
        job.heartbeat_at = now
        if job.retry_count < job.max_retries:
            job.retry_count += 1
            job.status = "pending"
        else:
            job.status = "failed"
            job.finished_at = now
        self.db.flush()
        return job

    def retry(self, *, job: IngestionJob) -> IngestionJob:
        job.status = "pending"
        job.retry_count = 0
        job.progress_percent = 0
        job.error_message = None
        job.result_json = None
        job.locked_by = None
        job.locked_at = None
        job.heartbeat_at = None
        job.started_at = None
        job.finished_at = None
        self.db.flush()
        return job

    def cancel_pending(self, *, job: IngestionJob) -> IngestionJob:
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
        self.db.flush()
        return job

    def recover_stuck_jobs(self, *, timeout_seconds: int) -> int:
        stale_before = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        jobs = list(
            self.db.scalars(
                select(IngestionJob).where(
                    IngestionJob.status == "running",
                    IngestionJob.heartbeat_at < stale_before,
                )
            )
        )
        for job in jobs:
            self.mark_failed(job=job, error_message="Worker heartbeat timed out")
        return len(jobs)
