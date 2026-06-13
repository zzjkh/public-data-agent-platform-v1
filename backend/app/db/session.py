from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        current_settings = settings or get_settings()
        _engine = create_engine(current_settings.database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(
            bind=get_engine(settings),
            autoflush=False,
            autocommit=False,
            class_=Session,
        )
    return _sessionmaker


def create_session(settings: Settings | None = None) -> Session:
    return get_sessionmaker(settings)()


def reset_session_state() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None
