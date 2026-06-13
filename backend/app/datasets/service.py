from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.dataset import OpenDataset
from app.db.models.ingestion_job import IngestionJob
from app.db.repositories.dataset import OpenDatasetRepository
from app.db.repositories.ingestion_job import IngestionJobRepository
from app.db.repositories.source_file import SourceFileRepository
from app.datasets.schemas import DatasetImportRequest


class DatasetNotFoundError(ValueError):
    pass


class DatasetImportRequestError(ValueError):
    pass


class OpenDatasetService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.datasets = OpenDatasetRepository(db)
        self.source_files = SourceFileRepository(db)
        self.jobs = IngestionJobRepository(db)

    def create_import_job(
        self,
        *,
        request: DatasetImportRequest,
        created_by: UUID | None,
    ) -> IngestionJob:
        self._validate_source_file(request.catalog_source_file_id, label="catalog")
        if request.fields_source_file_id is not None:
            self._validate_source_file(request.fields_source_file_id, label="fields")

        job = self.jobs.create(
            job_type="import_open_datasets",
            target_type="source_file",
            target_id=request.catalog_source_file_id,
            payload_json={
                "catalog_source_file_id": str(request.catalog_source_file_id),
                "fields_source_file_id": (
                    str(request.fields_source_file_id)
                    if request.fields_source_file_id is not None
                    else None
                ),
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

    def list_datasets(
        self,
        *,
        page: int,
        page_size: int,
        keyword: str | None,
        category: str | None,
        department: str | None,
        status: str | None,
    ) -> tuple[list[OpenDataset], int]:
        return self.datasets.list(
            page=page,
            page_size=page_size,
            keyword=keyword,
            category=category,
            department=department,
            status=status,
        )

    def get_dataset(self, *, dataset_id: UUID) -> OpenDataset:
        dataset = self.datasets.get_by_id(dataset_id)
        if dataset is None:
            raise DatasetNotFoundError("Dataset not found")
        return dataset

    def list_fields(self, *, dataset_id: UUID):
        return self.datasets.list_fields(dataset_id=dataset_id)

    def _validate_source_file(self, source_file_id: UUID, *, label: str) -> None:
        source_file = self.source_files.get_by_id(source_file_id)
        if source_file is None:
            raise DatasetImportRequestError(f"{label} source file not found")
        if source_file.file_type not in {"csv", "xlsx"}:
            raise DatasetImportRequestError(
                f"{label} source file must be csv or xlsx, got {source_file.file_type}"
            )
