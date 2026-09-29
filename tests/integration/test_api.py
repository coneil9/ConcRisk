from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from concrisk.api.main import app
from concrisk.db.session import get_session
from tests.integration.seeds import (
    seed_filing,
    seed_fund,
    seed_position,
    seed_security,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """TestClient that shares the db_session fixture — so seeds committed
    in the test are visible to the API handlers."""

    def _override_get_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def _seed_berkshire_portfolio(session: Session, period: date = date(2026, 3, 31)) -> None:
    berk = seed_fund(session, "1067983", "Berkshire Hathaway")
    aapl = seed_security(session, "037833100", "AAPL", "APPLE INC", sector="Tech")
    msft = seed_security(session, "594918104", "MSFT", "MICROSOFT CORP", sector="Tech")
    bac = seed_security(session, "060505104", "BAC", "BANK OF AMERICA")
    filing = seed_filing(session, berk, period, f"berk-{period.isoformat()}")
    seed_position(session, filing, aapl, Decimal("100"), Decimal("50"))
    seed_position(session, filing, msft, Decimal("100"), Decimal("30"))
    seed_position(session, filing, bac, Decimal("100"), Decimal("20"))
    session.commit()


def test_health_still_returns_200(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_funds_lists_tracked_with_latest_quarter(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session)
    r = client.get("/funds")
    assert r.status_code == 200
    body = r.json()
    assert "data_notes" in body
    by_cik = {f["cik"]: f for f in body["funds"]}
    assert by_cik["0001067983"]["latest_quarter"] == "2026Q1"
    assert by_cik["0001067983"]["name"] == "Berkshire Hathaway"
    # Untouched tracked funds report null latest_quarter.
    assert by_cik["0001350694"]["latest_quarter"] is None


def test_quarters_endpoint(client: TestClient, db_session: Session) -> None:
    berk = seed_fund(db_session, "1067983", "Berkshire")
    aapl = seed_security(db_session, "037833100", "AAPL", "APPLE")
    for p in (date(2025, 12, 31), date(2026, 3, 31)):
        f = seed_filing(db_session, berk, p, f"acc-{p}")
        seed_position(db_session, f, aapl, Decimal("1"), Decimal("1"))
    db_session.commit()

    r = client.get("/funds/1067983/quarters")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_cik"] == "0001067983"
    assert body["quarters"] == ["2025Q4", "2026Q1"]


def test_quarters_endpoint_unknown_fund_404(client: TestClient) -> None:
    r = client.get("/funds/9999999/quarters")
    assert r.status_code == 404


def test_holdings_endpoint_returns_weighted_positions(
    client: TestClient, db_session: Session
) -> None:
    # HAND-COMPUTED: total 100, weights [0.5, 0.3, 0.2].
    _seed_berkshire_portfolio(db_session)
    r = client.get("/funds/1067983/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["quarter"] == "2026Q1"
    assert body["total_value_usd"] == 100.0
    weights_by_ticker = {h["ticker"]: h["weight"] for h in body["holdings"]}
    assert weights_by_ticker["AAPL"] == pytest.approx(0.5)
    assert weights_by_ticker["MSFT"] == pytest.approx(0.3)
    assert weights_by_ticker["BAC"] == pytest.approx(0.2)
    # Sorted desc by weight.
    assert [h["ticker"] for h in body["holdings"]] == ["AAPL", "MSFT", "BAC"]


def test_holdings_top_param_truncates(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session)
    r = client.get("/funds/1067983/holdings?top=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["holdings"]) == 2
    assert [h["ticker"] for h in body["holdings"]] == ["AAPL", "MSFT"]


def test_concentration_endpoint(client: TestClient, db_session: Session) -> None:
    # HAND-COMPUTED: weights (0.5, 0.3, 0.2). HHI = 0.25+0.09+0.04 = 0.38.
    _seed_berkshire_portfolio(db_session)
    r = client.get("/funds/1067983/concentration")
    assert r.status_code == 200
    body = r.json()
    assert body["quarter"] == "2026Q1"
    assert body["hhi"] == pytest.approx(0.38)
    assert body["effective_n"] == pytest.approx(1 / 0.38)
    assert body["top5"] == pytest.approx(1.0)
    assert body["largest_issuer"]["issuer_key"] == "AAPL"
    assert body["largest_issuer"]["weight"] == pytest.approx(0.5)


def test_concentration_history_endpoint(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session, period=date(2025, 12, 31))
    _seed_berkshire_portfolio(db_session, period=date(2026, 3, 31))
    r = client.get("/funds/1067983/concentration/history")
    assert r.status_code == 200
    body = r.json()
    assert [e["quarter"] for e in body["history"]] == ["2025Q4", "2026Q1"]
    for entry in body["history"]:
        assert entry["hhi"] == pytest.approx(0.38)


def test_exposure_endpoint(client: TestClient, db_session: Session) -> None:
    # HAND-COMPUTED: AAPL 50% of Berkshire's $100 portfolio.
    _seed_berkshire_portfolio(db_session)
    r = client.get("/exposure/AAPL")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert len(body["exposures"]) == 1
    e = body["exposures"][0]
    assert e["fund_cik"] == "0001067983"
    assert e["weight"] == pytest.approx(0.5)


def test_exposure_unknown_ticker_returns_404(client: TestClient) -> None:
    r = client.get("/exposure/NOSUCHTICKER")
    assert r.status_code == 404


def test_breaches_endpoint_with_berkshire_override(client: TestClient, db_session: Session) -> None:
    # HAND-COMPUTED: Berkshire's AAPL at 50% → within override warning
    # range (0.30-0.40? no, above 0.40). breach: 50 > 40 → breach.
    _seed_berkshire_portfolio(db_session)
    r = client.get("/breaches")
    assert r.status_code == 200
    body = r.json()
    aapl_hits = [
        b for b in body["breaches"] if b["rule_id"] == "single_issuer" and b["scope_key"] == "AAPL"
    ]
    assert len(aapl_hits) == 1
    assert aapl_hits[0]["severity"] == "breach"
    assert aapl_hits[0]["threshold"] == 0.40  # Berkshire override


def test_breaches_severity_filter(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session)
    r = client.get("/breaches?severity=warning")
    assert r.status_code == 200
    body = r.json()
    # AAPL @ 0.50 → breach severity; filter should exclude it.
    assert all(b["severity"] == "warning" for b in body["breaches"])


def test_compare_endpoint(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session)
    # Seed a second fund with a different portfolio shape.
    bw = seed_fund(db_session, "1350694", "Bridgewater")
    sec = seed_security(db_session, "037833100", "AAPL", "APPLE")
    filing = seed_filing(db_session, bw, date(2026, 3, 31), "bw-1")
    seed_position(db_session, filing, sec, Decimal("1"), Decimal("100"))
    db_session.commit()

    r = client.get("/compare?ciks=1067983,1350694&quarter=2026Q1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["funds"]) == 2
    ciks = [f["fund_cik"] for f in body["funds"]]
    assert ciks == ["0001067983", "0001350694"]


def test_compare_requires_at_least_two_ciks(client: TestClient) -> None:
    r = client.get("/compare?ciks=1067983")
    assert r.status_code == 400


def test_compare_unknown_cik_404(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session)
    r = client.get("/compare?ciks=1067983,9999999")
    assert r.status_code == 404


def test_bad_quarter_string_returns_400(client: TestClient, db_session: Session) -> None:
    _seed_berkshire_portfolio(db_session)
    r = client.get("/funds/1067983/holdings?quarter=nope")
    assert r.status_code == 400
