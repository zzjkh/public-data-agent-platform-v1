from __future__ import annotations

from pathlib import Path

from app.db.models.ingestion_job import IngestionJob
from app.db.models.user import User
from app.ingestion.worker import run_worker_once
from tests.helpers import make_test_settings, make_test_client


def test_worker_runs_registered_handler(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)

    with SessionLocal() as db:
        job = IngestionJob(job_type="noop", target_type="source_file", payload_json={})
        db.add(job)
        db.commit()

        processed = run_worker_once(
            db=db,
            settings=settings,
            handlers={"noop": lambda _db, _job: {"ok": True}},
        )
        db.refresh(job)

    assert processed is not None
    assert job.status == "success"
    assert job.progress_percent == 100
    assert job.result_json == {"ok": True}
    assert job.locked_by is None


def test_worker_marks_unknown_job_type_failed_without_retries(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)

    with SessionLocal() as db:
        job = IngestionJob(
            job_type="unknown",
            target_type="source_file",
            payload_json={},
            max_retries=0,
        )
        db.add(job)
        db.commit()

        processed = run_worker_once(db=db, settings=settings, handlers={})
        db.refresh(job)

    assert processed is not None
    assert job.status == "failed"
    assert "No handler registered" in (job.error_message or "")


def test_worker_rolls_back_flush_error_before_marking_failed(tmp_path: Path) -> None:
    _, SessionLocal = make_test_client(tmp_path)
    settings = make_test_settings(tmp_path)

    def handler_with_flush_error(db, _job):
        db.add_all(
            [
                User(username="duplicate-worker-user", password_hash="hash", role="user"),
                User(username="duplicate-worker-user", password_hash="hash", role="user"),
            ]
        )
        db.flush()

    with SessionLocal() as db:
        job = IngestionJob(
            job_type="flush_error",
            target_type="source_file",
            payload_json={},
            max_retries=0,
        )
        db.add(job)
        db.commit()

        processed = run_worker_once(
            db=db,
            settings=settings,
            handlers={"flush_error": handler_with_flush_error},
        )
        db.refresh(job)

    assert processed is not None
    assert job.status == "failed"
    assert job.error_message
