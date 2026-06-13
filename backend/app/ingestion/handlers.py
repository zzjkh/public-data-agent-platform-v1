from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.datasets.metrics_importer import MetricImporter, MetricImportOptions
from app.db.models.ingestion_job import IngestionJob
from app.db.repositories.source_file import SourceFileRepository
from app.datasets.importers import OpenDatasetImporter
from app.documents.service import DocumentService
from app.files.storage import LocalFileStorage
from app.ingestion.chunking import ChunkingService
from app.ingestion.embeddings import ChunkEmbeddingService
from app.ingestion.parsers.ocr_engine import OcrEngine, RapidOcrEngine, TesseractOcrEngine
from app.ingestion.worker import JobHandler
from app.llm.embedding_provider import (
    EmbeddingProvider,
    RemoteHttpEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from app.semantic.service import SemanticMetadataService


def get_default_job_handlers(settings: Settings) -> dict[str, JobHandler]:
    return {
        "parse_policy_document": lambda db, job: parse_policy_document_job(
            db=db,
            job=job,
            settings=settings,
        ),
        "build_rag_chunks": lambda db, job: build_rag_chunks_job(
            db=db,
            job=job,
            settings=settings,
        ),
        "build_chunk_embeddings": lambda db, job: build_chunk_embeddings_job(
            db=db,
            job=job,
            settings=settings,
        ),
        "import_open_datasets": lambda db, job: import_open_datasets_job(
            db=db,
            job=job,
            settings=settings,
        ),
        "import_metric_values": lambda db, job: import_metric_values_job(
            db=db,
            job=job,
            settings=settings,
        ),
        "rebuild_semantic_metadata": lambda db, job: rebuild_semantic_metadata_job(
            db=db,
            job=job,
            settings=settings,
        ),
    }


def parse_policy_document_job(
    *,
    db: Session,
    job: IngestionJob,
    settings: Settings,
) -> dict:
    source_file_id = resolve_source_file_id(job)
    document_id = parse_optional_uuid(job.payload_json.get("document_id"))
    source_file = SourceFileRepository(db).get_by_id(source_file_id)
    if source_file is None:
        raise ValueError("Source file not found")

    parser_type = job.payload_json.get("parser_type") or infer_parser_type(source_file.file_type)
    if parser_type not in ("html", "pdf_text", "pdf_ocr"):
        raise ValueError(f"Unsupported parser_type for current stage: {parser_type}")

    service = DocumentService(db, LocalFileStorage(settings.file_storage_root))
    if parser_type == "html":
        version, elements, reused = service.parse_html_source_file(
            source_file_id=source_file_id,
            document_id=document_id,
        )
    elif parser_type == "pdf_text":
        version, elements, reused = service.parse_pdf_text_source_file(
            source_file_id=source_file_id,
            document_id=document_id,
            table_extraction_enabled=settings.pdf_table_extraction_enabled,
            agent_refine_enabled=settings.pdf_agent_refine_enabled,
        )
    else:
        if not settings.ocr_enabled:
            source_file.parse_status = "failed"
            source_file.error_message = "OCR is disabled by OCR_ENABLED=false"
            db.flush()
            raise ValueError(source_file.error_message)
        version, elements, reused = service.parse_pdf_ocr_source_file(
            source_file_id=source_file_id,
            document_id=document_id,
            ocr_engine=build_ocr_engine(settings),
            lang=settings.ocr_lang,
            render_dpi=settings.ocr_render_dpi,
            min_text_length=settings.ocr_min_text_length,
            agent_refine_enabled=settings.ocr_agent_refine_enabled,
        )

    return {
        "document_id": str(version.document_id),
        "version_id": str(version.id),
        "parser_type": version.parser_type,
        "element_count": len(elements),
        "reused_existing_version": reused,
    }


def build_rag_chunks_job(
    *,
    db: Session,
    job: IngestionJob,
    settings: Settings,
) -> dict:
    _ = settings
    version_id = resolve_document_version_id(job)
    chunk_strategy = str(job.payload_json.get("chunk_strategy") or "section")
    result = ChunkingService(db).build_chunks(
        version_id=version_id,
        chunk_strategy=chunk_strategy,
    )
    return {
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "chunk_strategy": chunk_strategy,
        "chunk_count": len(result.chunks),
        "reused_existing_chunks": result.reused_count,
    }


def build_chunk_embeddings_job(
    *,
    db: Session,
    job: IngestionJob,
    settings: Settings,
) -> dict:
    version_id = resolve_document_version_id(job)
    embedding_model = str(job.payload_json.get("embedding_model") or settings.embedding_model)
    embedding_version = str(job.payload_json.get("embedding_version") or settings.embedding_version)
    embedding_dim = int(job.payload_json.get("embedding_dim") or settings.embedding_dim)
    batch_size = int(job.payload_json.get("batch_size") or settings.embedding_batch_size)
    provider = build_embedding_provider(
        settings,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
    )
    result = ChunkEmbeddingService(db).build_embeddings(
        version_id=version_id,
        provider=provider,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embedding_version=embedding_version,
        batch_size=batch_size,
        max_retries=settings.embedding_max_retries,
    )
    return {
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "embedding_model": result.embedding_model,
        "embedding_dim": result.embedding_dim,
        "embedding_version": result.embedding_version,
        "chunk_count": result.chunk_count,
        "created_embeddings": result.created_count,
        "reused_existing_embeddings": result.reused_count,
    }


def import_open_datasets_job(
    *,
    db: Session,
    job: IngestionJob,
    settings: Settings,
) -> dict:
    catalog_source_file_id = resolve_dataset_catalog_source_file_id(job)
    fields_source_file_id = parse_optional_uuid(job.payload_json.get("fields_source_file_id"))
    result = OpenDatasetImporter(db, LocalFileStorage(settings.file_storage_root)).import_from_source_files(
        catalog_source_file_id=catalog_source_file_id,
        fields_source_file_id=fields_source_file_id,
    )
    return {
        "catalog_source_file_id": str(result.catalog_source_file_id),
        "fields_source_file_id": (
            str(result.fields_source_file_id) if result.fields_source_file_id is not None else None
        ),
        "catalog_rows": result.catalog_rows,
        "field_rows": result.field_rows,
        "datasets_created": result.datasets_created,
        "datasets_updated": result.datasets_updated,
        "fields_created": result.fields_created,
        "fields_updated": result.fields_updated,
        "field_rows_skipped": result.field_rows_skipped,
    }


def import_metric_values_job(
    *,
    db: Session,
    job: IngestionJob,
    settings: Settings,
) -> dict:
    source_file_id = resolve_metric_source_file_id(job)
    result = MetricImporter(db, LocalFileStorage(settings.file_storage_root)).import_from_source_file(
        source_file_id=source_file_id,
        options=MetricImportOptions(
            format=str(job.payload_json.get("format") or "auto"),
            default_region_code=job.payload_json.get("default_region_code"),
            default_region_name=str(job.payload_json.get("default_region_name") or "北京市"),
            default_stat_period=str(job.payload_json.get("default_stat_period") or "annual"),
            default_data_version=str(job.payload_json.get("default_data_version") or "v1"),
            default_source=job.payload_json.get("default_source"),
            default_source_url=job.payload_json.get("default_source_url"),
            metric_mappings=job.payload_json.get("metric_mappings"),
        ),
    )
    return {
        "source_file_id": str(result.source_file_id),
        "input_format": result.input_format,
        "source_rows": result.source_rows,
        "metric_rows": result.metric_rows,
        "metrics_created": result.metrics_created,
        "metrics_updated": result.metrics_updated,
        "values_created": result.values_created,
        "values_updated": result.values_updated,
        "rows_skipped": result.rows_skipped,
    }


def rebuild_semantic_metadata_job(
    *,
    db: Session,
    job: IngestionJob,
    settings: Settings,
) -> dict:
    embedding_model = str(job.payload_json.get("embedding_model") or settings.embedding_model)
    embedding_version = str(job.payload_json.get("embedding_version") or settings.embedding_version)
    embedding_dim = int(job.payload_json.get("embedding_dim") or settings.embedding_dim)
    batch_size = int(job.payload_json.get("batch_size") or settings.embedding_batch_size)
    metadata_types = job.payload_json.get("metadata_types")
    force_rebuild = bool(job.payload_json.get("force_rebuild") or False)
    provider = build_embedding_provider(
        settings,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
    )
    result = SemanticMetadataService(db, settings).rebuild_metadata(
        metadata_types=metadata_types,
        provider=provider,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        embedding_version=embedding_version,
        batch_size=batch_size,
        max_retries=settings.embedding_max_retries,
        force_rebuild=force_rebuild,
    )
    return {
        "metadata_types": result.metadata_types,
        "item_count": result.item_count,
        "items_created": result.items_created,
        "items_updated": result.items_updated,
        "embeddings_created": result.embeddings_created,
        "embeddings_reused": result.embeddings_reused,
        "embeddings_deleted": result.embeddings_deleted,
        "embedding_model": result.embedding_model,
        "embedding_dim": result.embedding_dim,
        "embedding_version": result.embedding_version,
    }


def resolve_source_file_id(job: IngestionJob) -> UUID:
    payload_source_file_id = parse_optional_uuid(job.payload_json.get("source_file_id"))
    if payload_source_file_id is not None:
        return payload_source_file_id
    if job.target_type == "source_file" and job.target_id is not None:
        return job.target_id
    raise ValueError("parse_policy_document requires source_file_id")


def resolve_document_version_id(job: IngestionJob) -> UUID:
    payload_version_id = parse_optional_uuid(job.payload_json.get("version_id"))
    if payload_version_id is not None:
        return payload_version_id
    if job.target_type == "document_version" and job.target_id is not None:
        return job.target_id
    raise ValueError("build_rag_chunks requires version_id")


def resolve_dataset_catalog_source_file_id(job: IngestionJob) -> UUID:
    payload_source_file_id = parse_optional_uuid(job.payload_json.get("catalog_source_file_id"))
    if payload_source_file_id is not None:
        return payload_source_file_id
    if job.target_type == "source_file" and job.target_id is not None:
        return job.target_id
    raise ValueError("import_open_datasets requires catalog_source_file_id")


def resolve_metric_source_file_id(job: IngestionJob) -> UUID:
    payload_source_file_id = parse_optional_uuid(job.payload_json.get("source_file_id"))
    if payload_source_file_id is not None:
        return payload_source_file_id
    if job.target_type == "source_file" and job.target_id is not None:
        return job.target_id
    raise ValueError("import_metric_values requires source_file_id")


def infer_parser_type(file_type: str) -> str:
    if file_type == "html":
        return "html"
    if file_type == "pdf":
        return "pdf_text"
    raise ValueError(f"No parser available for file_type={file_type}")


def build_ocr_engine(settings: Settings) -> OcrEngine:
    if settings.ocr_engine == "rapidocr":
        return RapidOcrEngine()
    if settings.ocr_engine == "tesseract":
        return TesseractOcrEngine()
    raise ValueError(f"Unsupported OCR_ENGINE: {settings.ocr_engine}")


def build_embedding_provider(
    settings: Settings,
    *,
    embedding_model: str,
    embedding_dim: int,
) -> EmbeddingProvider:
    if settings.embedding_provider == "sentence_transformers":
        return SentenceTransformerEmbeddingProvider(
            model_name=embedding_model,
            embedding_dim=embedding_dim,
            normalize_embeddings=settings.embedding_normalize,
            device=settings.embedding_device,
            query_instruction=settings.embedding_query_instruction,
        )
    if settings.embedding_provider == "remote_http":
        if not settings.embedding_remote_url:
            raise ValueError("EMBEDDING_REMOTE_URL is required for remote_http provider")
        return RemoteHttpEmbeddingProvider(
            model_name=embedding_model,
            embedding_dim=embedding_dim,
            endpoint_url=settings.embedding_remote_url,
            api_format=settings.embedding_remote_api_format,
            api_key=settings.embedding_remote_api_key,
            timeout_seconds=settings.embedding_request_timeout_seconds,
            normalize_embeddings=settings.embedding_normalize,
            trust_env=settings.embedding_remote_trust_env,
            query_instruction=settings.embedding_query_instruction,
        )
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")


def parse_optional_uuid(value: object) -> UUID | None:
    if value in (None, ""):
        return None
    return UUID(str(value))
