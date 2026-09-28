from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import EtlReject, EtlRun, Security
from concrisk.etl.openfigi import (
    OpenFigiClient,
    SecurityMapping,
    load_cached_mappings,
    map_cusips,
    upsert_mappings,
)

pytestmark = pytest.mark.integration


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _seed_run(session: Session) -> int:
    run = EtlRun(started_at=datetime.now(UTC), status="running")
    session.add(run)
    session.commit()
    return run.id


def test_load_cached_mappings_returns_resolved_rows(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Security(cusip="A", figi="F-A", ticker="AA", mapped_at=now),
            Security(cusip="B", figi=None, mapped_at=now),  # unresolved, cached
            Security(cusip="C", figi="F-C", ticker="CC", mapped_at=None),  # not cached
        ]
    )
    db_session.commit()

    cached = load_cached_mappings(db_session, ["A", "B", "C", "D"])

    assert set(cached.keys()) == {"A", "B"}
    assert cached["A"] is not None
    assert cached["A"].ticker == "AA"
    assert cached["B"] is None


def test_upsert_mappings_writes_rejects_for_unresolved(
    db_session: Session,
) -> None:
    run_id = _seed_run(db_session)

    upsert_mappings(
        db_session,
        {
            "037833100": SecurityMapping(
                cusip="037833100",
                figi="BBG000B9XRY4",
                ticker="AAPL",
                name="APPLE INC",
                security_type="Common Stock",
                exch_code="US",
            ),
            "999999999": None,
        },
        run_id,
    )
    db_session.commit()

    apple = db_session.execute(select(Security).where(Security.cusip == "037833100")).scalar_one()
    unresolved = db_session.execute(
        select(Security).where(Security.cusip == "999999999")
    ).scalar_one()

    assert apple.ticker == "AAPL"
    assert apple.mapped_at is not None
    assert unresolved.figi is None
    assert unresolved.mapped_at is not None  # so next run doesn't retry

    rejects = (
        db_session.execute(select(EtlReject).where(EtlReject.source == "openfigi")).scalars().all()
    )
    assert len(rejects) == 1
    assert rejects[0].record == {"cusip": "999999999"}


def test_map_cusips_cache_first_skips_http(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "")
    run_id = _seed_run(db_session)
    now = datetime.now(UTC)
    db_session.add(
        Security(
            cusip="037833100",
            figi="BBG000B9XRY4",
            ticker="AAPL",
            mapped_at=now,
        )
    )
    db_session.commit()

    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=[{"data": []}])

    with OpenFigiClient(client=_client(handler)) as figi:
        out = map_cusips(db_session, figi, ["037833100"], run_id)

    assert calls["n"] == 0
    assert out["037833100"] is not None
    assert out["037833100"].ticker == "AAPL"


def test_map_cusips_new_cusip_hits_api_and_upserts(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "")
    run_id = _seed_run(db_session)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "data": [
                        {
                            "figi": "BBG000B9XRY4",
                            "ticker": "AAPL",
                            "name": "APPLE INC",
                            "securityType": "Common Stock",
                            "exchCode": "US",
                        }
                    ]
                }
            ],
        )

    with OpenFigiClient(client=_client(handler)) as figi:
        out = map_cusips(db_session, figi, ["037833100"], run_id)
    db_session.commit()

    assert out["037833100"] is not None
    row = db_session.execute(select(Security).where(Security.cusip == "037833100")).scalar_one()
    assert row.ticker == "AAPL"
    assert row.figi == "BBG000B9XRY4"
    assert row.mapped_at is not None
