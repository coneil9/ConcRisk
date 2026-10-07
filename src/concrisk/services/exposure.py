from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
from sqlalchemy.orm import Session

from concrisk.risk import compute_weights, load_issuer_map
from concrisk.risk.lookthrough import apply_lookthrough
from concrisk.services.etf import load_latest_constituents
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
    # Phase 7 — only populated when lookthrough=True.
    lookthrough_weight: float | None = None
    lookthrough_coverage: float | None = None


def issuer_exposure_across_funds(
    session: Session,
    *,
    ticker: str,
    period_of_report: date | None = None,
    lookthrough: bool = False,
) -> list[ExposureRow]:
    """Cross-fund exposure to `ticker`. Matches by rolled-up issuer_key
    so GOOG/GOOGL sum together. If period_of_report is None, each fund
    uses its own latest available quarter. If lookthrough=True, each
    row also includes the ticker's expanded ETF weight."""
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

        lookthrough_w: float | None = None
        lookthrough_cov: float | None = None
        if lookthrough:
            constituents = load_latest_constituents(session, as_of_cutoff=period)
            lt = apply_lookthrough(weighted, constituents)
            lookthrough_cov = lt.coverage
            lookthrough_w = float(lt.weights.get(ticker_upper, 0.0) or 0.0)

        matches = cast(pd.DataFrame, weighted[weighted["issuer_key"] == target_issuer])
        if matches.empty and not (lookthrough_w and lookthrough_w > 0):
            continue
        total_weight = float(cast(pd.Series, matches["weight"]).sum()) if not matches.empty else 0.0
        total_value = (
            float(cast(pd.Series, matches["value_usd"]).sum()) if not matches.empty else 0.0
        )
        first_ticker = matches.iloc[0]["ticker"] if not matches.empty else None
        has_ticker = first_ticker is not None and pd.notna(first_ticker)
        display_ticker = str(first_ticker) if has_ticker else ticker_upper
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
                lookthrough_weight=lookthrough_w,
                lookthrough_coverage=lookthrough_cov,
            )
        )
    return out
