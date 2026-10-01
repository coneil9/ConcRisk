from datetime import date
from typing import cast

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import Filing, Fund, Position, Security
from concrisk.risk import add_issuer_key

HOLDINGS_COLUMNS = [
    "security_id",
    "cusip",
    "ticker",
    "name",
    "sector",
    "is_etf",
    "shares",
    "value_usd",
    "put_call",
]


def normalize_cik(cik: str) -> str:
    """Accept any padding; return 10-digit zero-padded string."""
    return str(int(cik)).zfill(10)


def get_fund(session: Session, cik: str) -> Fund | None:
    return session.execute(select(Fund).where(Fund.cik == normalize_cik(cik))).scalar_one_or_none()


def build_holdings_df(
    session: Session,
    *,
    cik: str,
    period_of_report: date,
    issuer_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Current holdings for (cik, period). Positions from all non-superseded
    filings for that (fund, period), aggregated per (security_id, put_call)
    so NEW HOLDINGS amendments merge into the base filing per SPEC §5.

    Returns an empty DataFrame with the right columns when the fund or
    period has no non-superseded positions — callers can just check
    `.empty`.
    """
    fund = get_fund(session, cik)
    if fund is None:
        return _empty_holdings_df(issuer_map is not None)

    stmt = (
        select(
            Position.security_id,
            Security.cusip,
            Security.ticker,
            Security.name,
            Security.sector,
            Security.is_etf,
            Position.shares,
            Position.value_usd,
            Position.put_call,
        )
        .join(Filing, Filing.id == Position.filing_id)
        .join(Security, Security.id == Position.security_id)
        .where(
            Filing.fund_id == fund.id,
            Filing.period_of_report == period_of_report,
            Filing.is_superseded.is_(False),
        )
    )
    rows = session.execute(stmt).all()
    if not rows:
        return _empty_holdings_df(issuer_map is not None)

    df = pd.DataFrame(rows, columns=HOLDINGS_COLUMNS)
    df["shares"] = cast(pd.Series, df["shares"]).astype(float)
    df["value_usd"] = cast(pd.Series, df["value_usd"]).astype(float)

    agg = cast(
        pd.DataFrame,
        df.groupby(["security_id", "put_call"], dropna=False, as_index=False).agg(
            {
                "cusip": "first",
                "ticker": "first",
                "name": "first",
                "sector": "first",
                "is_etf": "first",
                "shares": "sum",
                "value_usd": "sum",
            }
        ),
    )

    if issuer_map is not None:
        agg = add_issuer_key(agg, issuer_map)
    return agg


def _empty_holdings_df(with_issuer_key: bool) -> pd.DataFrame:
    cols = list(HOLDINGS_COLUMNS)
    if with_issuer_key:
        cols.append("issuer_key")
    return pd.DataFrame(columns=cols)
