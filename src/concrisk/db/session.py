import logging
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from concrisk.config import get_settings

logger = logging.getLogger(__name__)


def _psycopg_url(url: str) -> str:
    # CLAUDE.md mandates the psycopg 3 driver, but SQLAlchemy defaults
    # `postgresql://` to psycopg2. Pin the driver here so .env stays neutral.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _build_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        _psycopg_url(str(settings.database_url)),
        pool_pre_ping=True,
        future=True,
    )


engine: Engine = _build_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
