from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from concrisk.chat import execute_tool
from tests.integration.seeds import (
    seed_filing,
    seed_fund,
    seed_position,
    seed_security,
)

pytestmark = pytest.mark.integration


def _seed_small_portfolio(session: Session, period: date = date(2026, 3, 31)) -> None:
    berk = seed_fund(session, "1067983", "Berkshire Hathaway")
    aapl = seed_security(session, "037833100", "AAPL", "APPLE INC", sector="Tech")
    msft = seed_security(session, "594918104", "MSFT", "MICROSOFT CORP", sector="Tech")
    filing = seed_filing(session, berk, period, f"berk-{period.isoformat()}")
    seed_position(session, filing, aapl, Decimal("100"), Decimal("60"))
    seed_position(session, filing, msft, Decimal("100"), Decimal("40"))
    session.commit()


def test_list_funds_returns_summaries(db_session: Session) -> None:
    _seed_small_portfolio(db_session)
    result = execute_tool("list_funds", {}, db_session)
    assert "funds" in result
    by_cik = {f["cik"]: f for f in result["funds"]}
    assert by_cik["0001067983"]["latest_quarter"] == "2026Q1"


def test_get_concentration_by_cik(db_session: Session) -> None:
    # HAND-COMPUTED: weights [0.6, 0.4] → HHI = 0.36 + 0.16 = 0.52.
    _seed_small_portfolio(db_session)
    result = execute_tool("get_concentration", {"fund": "0001067983"}, db_session)
    assert result["fund_name"] == "Berkshire Hathaway"
    assert result["quarter"] == "2026Q1"
    assert result["hhi"] == pytest.approx(0.52)
    assert result["largest_issuer"]["issuer_key"] == "AAPL"
    assert result["largest_issuer"]["weight"] == pytest.approx(0.6)
    assert "data_notes" in result


def test_get_concentration_by_name(db_session: Session) -> None:
    _seed_small_portfolio(db_session)
    result = execute_tool("get_concentration", {"fund": "Berkshire"}, db_session)
    assert result["fund_cik"] == "0001067983"


def test_get_concentration_unknown_fund(db_session: Session) -> None:
    result = execute_tool("get_concentration", {"fund": "Xyzzy Blarg"}, db_session)
    assert result["error"] == "unknown_fund"


def test_get_concentration_ambiguous_fund(db_session: Session) -> None:
    result = execute_tool("get_concentration", {"fund": "Management"}, db_session)
    # 'Management' matches Point72, Pershing Square, Tiger Global, ...
    assert result["error"] == "ambiguous_fund"
    assert len(result["candidates"]) >= 2


def test_get_concentration_no_data(db_session: Session) -> None:
    # Seeded fund exists in config but no filings loaded for it.
    result = execute_tool("get_concentration", {"fund": "Renaissance Technologies"}, db_session)
    assert result["error"] == "no_data"


def test_get_holdings_returns_sorted_positions(db_session: Session) -> None:
    _seed_small_portfolio(db_session)
    result = execute_tool("get_holdings", {"fund": "1067983", "top": 5}, db_session)
    tickers = [h["ticker"] for h in result["holdings"]]
    assert tickers == ["AAPL", "MSFT"]  # sorted desc by weight
    assert result["holdings"][0]["weight"] == pytest.approx(0.6)


def test_get_exposure_by_ticker(db_session: Session) -> None:
    _seed_small_portfolio(db_session)
    result = execute_tool("get_exposure", {"ticker": "AAPL"}, db_session)
    assert result["ticker"] == "AAPL"
    assert len(result["exposures"]) == 1
    assert result["exposures"][0]["weight"] == pytest.approx(0.6)


def test_get_exposure_no_holders(db_session: Session) -> None:
    result = execute_tool("get_exposure", {"ticker": "NOSUCHTICKER"}, db_session)
    assert result["error"] == "no_data"


def test_get_breaches_picks_up_berkshire_override(db_session: Session) -> None:
    # HAND-COMPUTED: AAPL at 60% → within Berkshire override (breach at 40%).
    _seed_small_portfolio(db_session)
    result = execute_tool("get_breaches", {"quarter": "2026Q1"}, db_session)
    aapl_hits = [
        b
        for b in result["breaches"]
        if b["rule_id"] == "single_issuer" and b["scope_key"] == "AAPL"
    ]
    assert len(aapl_hits) == 1
    assert aapl_hits[0]["severity"] == "breach"
    assert aapl_hits[0]["threshold"] == 0.40


def test_compare_funds(db_session: Session) -> None:
    _seed_small_portfolio(db_session)
    # Seed a second fund
    bw = seed_fund(db_session, "1350694", "Bridgewater")
    sec = seed_security(db_session, "037833100", "AAPL", "APPLE")
    f = seed_filing(db_session, bw, date(2026, 3, 31), "bw-1")
    seed_position(db_session, f, sec, Decimal("1"), Decimal("100"))
    db_session.commit()

    result = execute_tool(
        "compare_funds",
        {"funds": ["1067983", "Bridgewater"], "quarter": "2026Q1"},
        db_session,
    )
    ciks = {f["fund_cik"] for f in result["funds"]}
    assert ciks == {"0001067983", "0001350694"}


def test_compare_funds_needs_at_least_two(db_session: Session) -> None:
    result = execute_tool("compare_funds", {"funds": ["1067983"]}, db_session)
    assert result["error"] == "need_at_least_two_funds"


def test_get_concentration_history(db_session: Session) -> None:
    _seed_small_portfolio(db_session, period=date(2025, 12, 31))
    _seed_small_portfolio(db_session, period=date(2026, 3, 31))
    result = execute_tool("get_concentration_history", {"fund": "1067983"}, db_session)
    quarters = [row["quarter"] for row in result["history"]]
    assert quarters == ["2025Q4", "2026Q1"]


def test_unknown_tool_returns_error(db_session: Session) -> None:
    result = execute_tool("no_such_tool", {}, db_session)
    assert result["error"] == "unknown_tool"


def test_tool_exception_is_caught(db_session: Session) -> None:
    # get_concentration expects 'fund' key — omitting it should surface via
    # tool_exception rather than bubbling out.
    result = execute_tool("get_concentration", {}, db_session)
    assert result["error"] == "tool_exception"
