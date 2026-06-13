from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.datasets.schemas import MetricImportRequest
from app.db.models.dataset import Metric, MetricValue
from app.db.models.ingestion_job import IngestionJob
from app.db.repositories.dataset import MetricRepository
from app.db.repositories.ingestion_job import IngestionJobRepository
from app.db.repositories.source_file import SourceFileRepository


class MetricNotFoundError(ValueError):
    pass


class MetricImportRequestError(ValueError):
    pass


class MetricService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.metrics = MetricRepository(db)
        self.source_files = SourceFileRepository(db)
        self.jobs = IngestionJobRepository(db)

    def create_import_job(
        self,
        *,
        request: MetricImportRequest,
        created_by: UUID | None,
    ) -> IngestionJob:
        self._validate_source_file(request.source_file_id)
        job = self.jobs.create(
            job_type="import_metric_values",
            target_type="source_file",
            target_id=request.source_file_id,
            payload_json={
                "source_file_id": str(request.source_file_id),
                "format": request.format,
                "default_region_code": request.default_region_code,
                "default_region_name": request.default_region_name,
                "default_stat_period": request.default_stat_period,
                "default_data_version": request.default_data_version,
                "default_source": request.default_source,
                "default_source_url": request.default_source_url,
                "metric_mappings": request.metric_mappings,
            },
            priority=request.priority,
            max_retries=(
                request.max_retries if request.max_retries is not None else self.settings.job_max_retries
            ),
            created_by=created_by,
        )
        self.db.commit()
        self.db.refresh(job)
        return job

    def list_metrics(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None,
        domain: str | None,
    ) -> tuple[list[Metric], int]:
        return self.metrics.list(page=page, page_size=page_size, keyword=keyword, domain=domain)

    def get_metric(self, *, metric_id: UUID) -> Metric:
        metric = self.metrics.get_by_id(metric_id)
        if metric is None:
            raise MetricNotFoundError("Metric not found")
        return metric

    def list_values(
        self,
        *,
        metric_id: UUID,
        region_name: str | None,
        stat_year_from: int | None,
        stat_year_to: int | None,
    ) -> list[MetricValue]:
        return self.metrics.list_values(
            metric_id=metric_id,
            region_name=region_name,
            stat_year_from=stat_year_from,
            stat_year_to=stat_year_to,
        )

    def _validate_source_file(self, source_file_id: UUID) -> None:
        source_file = self.source_files.get_by_id(source_file_id)
        if source_file is None:
            raise MetricImportRequestError("Metric source file not found")
        if source_file.file_type not in {"csv", "xlsx"}:
            raise MetricImportRequestError(
                f"Metric source file must be csv or xlsx, got {source_file.file_type}"
            )
