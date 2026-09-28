from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
from sqlalchemy.orm import Session

from concrisk.risk import compute_weights, load_issuer_map
from concrisk.services.funds import latest_period_for_fund, list_tracked_funds
from concrisk.services.holdings import build_holdings_df
from concrisk.services.quarters import format_quarter

ISSUER_MAP_YAML = Path("config/issuer_map.yaml")


@dataclass(frozen=True)
class ExposureRow:
    fund_cik: str
    fund_name: str
    quarter: str
    as_of: date
    weight: float
    value_usd: float
    ticker: str
    issuer_key: str


def issuer_exposure_across_funds(
    session: Session,
    *,
    ticker: str,
    period_of_report: date | None = None,
) -> list[ExposureRow]:
    """Cross-fund exposure to `ticker`. Matches by rolled-up issuer_key
    so GOOG/GOOGL sum together. If period_of_report is None, each fund
    uses its own latest available quarter."""
    ticker_upper = ticker.upper()
    issuer_map = load_issuer_map(ISSUER_MAP_YAML)
    target_issuer = issuer_map.get(ticker_upper, ticker_upper)

    out: list[ExposureRow] = []
    for cik, name in list_tracked_funds():
        period = period_of_report or latest_period_for_fund(session, cik)
        if period is None:
            continue
        holdings = build_holdings_df(
            session, cik=cik, period_of_report=period, issuer_map=issuer_map
        )
        if holdings.empty:
            continue
        weighted = compute_weights(holdings)
        matches = cast(pd.DataFrame, weighted[weighted["issuer_key"] == target_issuer])
        if matches.empty:
            continue
        total_weight = float(cast(pd.Series, matches["weight"]).sum())
        total_value = float(cast(pd.Series, matches["value_usd"]).sum())
        first_ticker = matches.iloc[0]["ticker"]
        display_ticker = str(first_ticker) if pd.notna(first_ticker) else ticker_upper
        out.append(
            ExposureRow(
                fund_cik=cik,
                fund_name=name,
                quarter=format_quarter(period),
                as_of=period,
                weight=total_weight,
                value_usd=total_value,
                ticker=display_ticker,
                issuer_key=target_issuer,
            )
        )
    return out
