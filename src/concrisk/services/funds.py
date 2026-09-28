from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from concrisk.db.models import Filing, Fund
from concrisk.services.holdings import get_fund, normalize_cik

FUNDS_YAML = Path("config/funds.yaml")


@dataclass(frozen=True)
class FundSummary:
    cik: str
    name: str
    latest_quarter_date: date | None


def list_tracked_funds() -> list[tuple[str, str]]:
    """Read config/funds.yaml → [(cik_padded, name), ...]."""
    data = yaml.safe_load(FUNDS_YAML.read_text())
    return [(str(f["cik"]).zfill(10), str(f["name"])) for f in data["funds"]]


def latest_period_for_fund(session: Session, cik: str) -> date | None:
    fund = get_fund(session, cik)
    if fund is None:
        return None
    return session.execute(
        select(func.max(Filing.period_of_report)).where(
            Filing.fund_id == fund.id, Filing.is_superseded.is_(False)
        )
    ).scalar_one_or_none()


def list_available_periods(session: Session, cik: str) -> list[date]:
    """Distinct non-superseded periods for a fund, sorted ascending."""
    fund = get_fund(session, cik)
    if fund is None:
        return []
    rows = (
        session.execute(
            select(Filing.period_of_report)
            .where(Filing.fund_id == fund.id, Filing.is_superseded.is_(False))
            .distinct()
            .order_by(Filing.period_of_report.asc())
        )
        .scalars()
        .all()
    )
    return list(rows)


def list_funds_with_latest_quarter(session: Session) -> list[FundSummary]:
    """For each tracked fund in funds.yaml, find its latest available period.
    Missing funds (never ingested) come back with `latest_quarter_date=None`."""
    tracked = list_tracked_funds()
    ciks = [c for c, _ in tracked]
    stmt = (
        select(Fund.cik, func.max(Filing.period_of_report))
        .select_from(Fund)
        .outerjoin(
            Filing,
            (Filing.fund_id == Fund.id) & (Filing.is_superseded.is_(False)),
        )
        .where(Fund.cik.in_(ciks))
        .group_by(Fund.cik)
    )
    latest_by_cik: dict[str, date | None] = {
        str(cik): period for cik, period in session.execute(stmt).all()
    }
    return [
        FundSummary(
            cik=normalize_cik(cik),
            name=name,
            latest_quarter_date=latest_by_cik.get(cik),
        )
        for cik, name in tracked
    ]
