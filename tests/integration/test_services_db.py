from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from concrisk.db.models import Filing, Fund, Position, Security
from concrisk.services import (
    breaches_for_quarter,
    build_holdings_df,
    get_concentration,
    latest_period_for_fund,
    list_funds_with_latest_quarter,
)

pytestmark = pytest.mark.integration


def _seed_fund(session: Session, cik: str, name: str) -> Fund:
    f = Fund(cik=cik.zfill(10), name=name)
    session.add(f)
    session.flush()
    return f


def _seed_security(
    session: Session, cusip: str, ticker: str, name: str, sector: str | None = None
) -> Security:
    s = Security(
        cusip=cusip,
        ticker=ticker,
        name=name,
        sector=sector,
        mapped_at=datetime.now(UTC),
    )
    session.add(s)
    session.flush()
    return s


def _seed_filing(
    session: Session,
    fund: Fund,
    period: date,
    accession: str,
    *,
    amendment: str | None = None,
    superseded: bool = False,
) -> Filing:
    f = Filing(
        fund_id=fund.id,
        accession_no=accession,
        form_type="13F-HR/A" if amendment else "13F-HR",
        period_of_report=period,
        filed_at=period,
        amendment_type=amendment,
        is_superseded=superseded,
        raw_path="/tmp/test.xml",
    )
    session.add(f)
    session.flush()
    return f


def _seed_position(
    session: Session,
    filing: Filing,
    security: Security,
    shares: Decimal,
    value: Decimal,
    *,
    put_call: str | None = None,
) -> Position:
    p = Position(
        filing_id=filing.id,
        security_id=security.id,
        put_call=put_call,
        shares=shares,
        share_type="SH",
        value_usd=value,
    )
    session.add(p)
    session.flush()
    return p


def test_build_holdings_single_filing(db_session: Session) -> None:
    fund = _seed_fund(db_session, "1067983", "Berkshire Hathaway")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE INC")
    filing = _seed_filing(db_session, fund, date(2026, 3, 31), "acc-1")
    _seed_position(db_session, filing, aapl, Decimal("100"), Decimal("22213"))
    db_session.commit()

    df = build_holdings_df(db_session, cik="1067983", period_of_report=date(2026, 3, 31))
    assert len(df) == 1
    assert float(df.iloc[0]["shares"]) == 100.0
    assert float(df.iloc[0]["value_usd"]) == 22213.0


def test_build_holdings_merges_new_holdings_amendment(db_session: Session) -> None:
    # HAND-COMPUTED: original AAPL 10M shares / $2M value + NEW HOLDINGS
    # amendment AAPL 2M / $500k. Both non-superseded → aggregate = 12M / $2.5M.
    fund = _seed_fund(db_session, "1067983", "Berkshire")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE INC")
    orig = _seed_filing(db_session, fund, date(2026, 3, 31), "acc-orig")
    amend = _seed_filing(db_session, fund, date(2026, 3, 31), "acc-amend", amendment="NEW HOLDINGS")
    _seed_position(db_session, orig, aapl, Decimal("10000000"), Decimal("2000000"))
    _seed_position(db_session, amend, aapl, Decimal("2000000"), Decimal("500000"))
    db_session.commit()

    df = build_holdings_df(db_session, cik="1067983", period_of_report=date(2026, 3, 31))
    assert len(df) == 1
    assert float(df.iloc[0]["shares"]) == 12_000_000.0
    assert float(df.iloc[0]["value_usd"]) == 2_500_000.0


def test_build_holdings_excludes_superseded(db_session: Session) -> None:
    # Original marked superseded (as if a RESTATEMENT amendment arrived).
    # Only the restatement's positions should appear.
    fund = _seed_fund(db_session, "1067983", "Berkshire")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE INC")
    orig = _seed_filing(db_session, fund, date(2026, 3, 31), "acc-orig", superseded=True)
    restate = _seed_filing(
        db_session, fund, date(2026, 3, 31), "acc-restate", amendment="RESTATEMENT"
    )
    _seed_position(db_session, orig, aapl, Decimal("100"), Decimal("22213"))
    _seed_position(db_session, restate, aapl, Decimal("50"), Decimal("11106"))
    db_session.commit()

    df = build_holdings_df(db_session, cik="1067983", period_of_report=date(2026, 3, 31))
    assert len(df) == 1
    assert float(df.iloc[0]["shares"]) == 50.0
    assert float(df.iloc[0]["value_usd"]) == 11106.0


def test_latest_period_for_fund(db_session: Session) -> None:
    fund = _seed_fund(db_session, "1067983", "Berkshire")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE")
    for period in (date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30)):
        f = _seed_filing(db_session, fund, period, f"acc-{period}")
        _seed_position(db_session, f, aapl, Decimal("1"), Decimal("1"))
    db_session.commit()

    assert latest_period_for_fund(db_session, "1067983") == date(2026, 6, 30)
    assert latest_period_for_fund(db_session, "9999999") is None


def test_list_funds_with_latest_quarter(db_session: Session) -> None:
    # Seed one tracked fund; leaves the other 14 tracked funds untouched
    # so their latest_quarter_date is None.
    fund = _seed_fund(db_session, "1067983", "Berkshire")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE")
    f = _seed_filing(db_session, fund, date(2026, 3, 31), "acc-1")
    _seed_position(db_session, f, aapl, Decimal("1"), Decimal("1"))
    db_session.commit()

    summaries = list_funds_with_latest_quarter(db_session)
    by_cik = {s.cik: s for s in summaries}
    assert by_cik["0001067983"].latest_quarter_date == date(2026, 3, 31)
    # A different tracked fund without data → None.
    assert by_cik["0001350694"].latest_quarter_date is None


def test_concentration_on_seeded_portfolio(db_session: Session) -> None:
    # HAND-COMPUTED: 3 equal positions → weights = (1/3, 1/3, 1/3).
    # HHI = 3 × (1/3)² = 1/3 ≈ 0.3333. effective_n = 3. top5 = 1.0.
    fund = _seed_fund(db_session, "1067983", "Berkshire")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE")
    msft = _seed_security(db_session, "594918104", "MSFT", "MICROSOFT")
    goog = _seed_security(db_session, "02079K305", "GOOGL", "ALPHABET")
    filing = _seed_filing(db_session, fund, date(2026, 3, 31), "acc-1")
    for sec in (aapl, msft, goog):
        _seed_position(db_session, filing, sec, Decimal("100"), Decimal("100"))
    db_session.commit()

    snap = get_concentration(db_session, cik="1067983", period_of_report=date(2026, 3, 31))
    assert snap is not None
    assert snap.hhi == pytest.approx(1 / 3)
    assert snap.effective_n == pytest.approx(3.0)
    assert snap.top5 == pytest.approx(1.0)


def test_breaches_picks_up_berkshire_override(db_session: Session) -> None:
    # HAND-COMPUTED: seeded Berkshire portfolio with AAPL at 35%
    # (value 35 out of total 100). Default single_issuer breach at 10%
    # would fire for any other fund; Berkshire's override lifts it to
    # warning=0.30 / breach=0.40 → 35% is a warning, not a breach.
    berk = _seed_fund(db_session, "1067983", "Berkshire")
    aapl = _seed_security(db_session, "037833100", "AAPL", "APPLE")
    msft = _seed_security(db_session, "594918104", "MSFT", "MICROSOFT")
    filing = _seed_filing(db_session, berk, date(2026, 3, 31), "berk-1")
    _seed_position(db_session, filing, aapl, Decimal("100"), Decimal("35"))
    _seed_position(db_session, filing, msft, Decimal("100"), Decimal("65"))
    db_session.commit()

    breaches = breaches_for_quarter(db_session, period_of_report=date(2026, 3, 31))
    aapl_hits = [b for b in breaches if b.rule_id == "single_issuer" and b.scope_key == "AAPL"]
    assert len(aapl_hits) == 1
    assert aapl_hits[0].severity == "warning"
    assert aapl_hits[0].threshold == 0.30
