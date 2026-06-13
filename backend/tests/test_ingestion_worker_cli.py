from __future__ import annotations

from app.scripts.run_ingestion_worker import run_worker_loop


def test_worker_loop_processes_one_job_in_once_mode() -> None:
    calls = iter([True])

    processed = run_worker_loop(
        process_next=lambda: next(calls),
        poll_seconds=1,
        once=True,
        sleep=lambda _: None,
    )

    assert processed == 1


def test_worker_loop_stops_after_configured_idle_cycles() -> None:
    calls = iter([True, False, False])
    sleeps: list[float] = []

    processed = run_worker_loop(
        process_next=lambda: next(calls),
        poll_seconds=2,
        stop_when_idle=True,
        max_idle_cycles=2,
        sleep=sleeps.append,
    )

    assert processed == 1
    assert sleeps == [2]
