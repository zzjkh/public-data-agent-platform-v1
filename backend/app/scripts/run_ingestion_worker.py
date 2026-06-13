from __future__ import annotations

import argparse
import time
from collections.abc import Callable

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger, reset_log_context
from app.db.session import create_session
from app.ingestion.handlers import get_default_job_handlers
from app.ingestion.worker import run_worker_once


def run_worker_loop(
    *,
    process_next: Callable[[], bool],
    poll_seconds: int,
    once: bool = False,
    stop_when_idle: bool = False,
    max_idle_cycles: int = 1,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if poll_seconds < 1:
        raise ValueError("poll_seconds must be positive")
    if max_idle_cycles < 1:
        raise ValueError("max_idle_cycles must be positive")

    processed_count = 0
    idle_cycles = 0
    while True:
        processed = process_next()
        if processed:
            processed_count += 1
            idle_cycles = 0
            if once:
                return processed_count
            continue

        idle_cycles += 1
        if once or (stop_when_idle and idle_cycles >= max_idle_cycles):
            return processed_count
        sleep(poll_seconds)


def build_process_next(settings: Settings) -> Callable[[], bool]:
    handlers = get_default_job_handlers(settings)

    def process_next() -> bool:
        reset_log_context()
        with create_session(settings) as db:
            return run_worker_once(db=db, settings=settings, handlers=handlers) is not None

    return process_next


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the PostgreSQL-backed ingestion worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    parser.add_argument(
        "--stop-when-idle",
        action="store_true",
        help="Exit after the queue remains empty for the configured idle cycles.",
    )
    parser.add_argument("--max-idle-cycles", type=int, default=2)
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=settings.job_poll_interval_seconds,
    )
    args = parser.parse_args()

    configure_logging(settings)
    logger = get_logger()
    logger.info(
        "ingestion_worker_started",
        worker_id=settings.worker_id,
        once=args.once,
        stop_when_idle=args.stop_when_idle,
    )
    try:
        processed_count = run_worker_loop(
            process_next=build_process_next(settings),
            poll_seconds=args.poll_seconds,
            once=args.once,
            stop_when_idle=args.stop_when_idle,
            max_idle_cycles=args.max_idle_cycles,
        )
    except KeyboardInterrupt:
        logger.info("ingestion_worker_stopped", reason="keyboard_interrupt")
        return
    logger.info("ingestion_worker_stopped", reason="completed", processed_count=processed_count)


if __name__ == "__main__":
    main()
