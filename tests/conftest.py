from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from concrisk.config import get_settings
from concrisk.db.models import Base
from concrisk.db.session import SessionLocal, engine


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def _ensure_schema() -> None:
    """Create all tables once per test session against the running DB."""
    Base.metadata.create_all(engine)


_TRUNCATE_PHASE1 = text(
    "TRUNCATE TABLE etl_rejects, etl_runs, positions, filings, "
    "securities, funds RESTART IDENTITY CASCADE"
)


@pytest.fixture
def db_session(_ensure_schema: None) -> Iterator[Session]:
    """Yield a fresh Session; truncate the Phase 1 tables before AND after
    the test so committed pipeline data doesn't leak between tests or into
    manual verification runs."""
    with SessionLocal() as session:
        session.execute(_TRUNCATE_PHASE1)
        session.commit()
        yield session
        session.rollback()
        session.execute(_TRUNCATE_PHASE1)
        session.commit()
