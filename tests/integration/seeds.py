"""Shared DB-seeding helpers for integration tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import Filing, Fund, Position, Security


def seed_security(
    session: Session,
    cusip: str,
    ticker: str,
    name: str,
    sector: str | None = None,
) -> Security:
    existing = session.execute(select(Security).where(Security.cusip == cusip)).scalar_one_or_none()
    if existing is not None:
        return existing
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


def seed_fund(session: Session, cik: str, name: str) -> Fund:
    padded = cik.zfill(10)
    existing = session.execute(select(Fund).where(Fund.cik == padded)).scalar_one_or_none()
    if existing is not None:
        return existing
    f = Fund(cik=padded, name=name)
    session.add(f)
    session.flush()
    return f


def seed_filing(
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


def seed_position(
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
