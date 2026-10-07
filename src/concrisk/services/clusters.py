from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import cast

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import Price, Security
from concrisk.risk import compute_weights, load_issuer_map
from concrisk.risk.correlation import Cluster, correlation_clusters
from concrisk.services.holdings import build_holdings_df

ISSUER_MAP_YAML = Path("config/issuer_map.yaml")
RETURN_WINDOW_DAYS = 252


@dataclass(frozen=True)
class ClusterResult:
    fund_cik: str
    quarter_period: date
    rho_threshold: float
    min_weight: float
    clusters: list[Cluster]
    missing_tickers: list[str]
    insufficient: bool


def _load_prices_wide(
    session: Session, tickers: list[str], end: date, window_days: int
) -> tuple[pd.DataFrame, list[str]]:
    """Return (wide prices DataFrame, missing_tickers)."""
    if not tickers:
        return pd.DataFrame(), []
    start = end - timedelta(days=int(window_days * 1.6))  # weekend cushion
    rows = session.execute(
        select(Security.ticker, Price.date, Price.close)
        .join(Price, Price.security_id == Security.id)
        .where(
            Security.ticker.in_(tickers),
            Price.date >= start,
            Price.date <= end,
        )
    ).all()
    if not rows:
        return pd.DataFrame(), list(tickers)
    df_long = pd.DataFrame(rows, columns=["ticker", "date", "close"])
    df_long["close"] = cast(pd.Series, df_long["close"]).astype(float)
    wide = df_long.pivot(index="date", columns="ticker", values="close")
    missing = [t for t in tickers if t not in wide.columns]
    return cast(pd.DataFrame, wide), missing


def get_clusters(
    session: Session,
    *,
    cik: str,
    period_of_report: date,
    rho_threshold: float = 0.7,
    min_weight: float = 0.005,
) -> ClusterResult | None:
    """Build correlation clusters for one fund-quarter. Returns None
    when the fund has no holdings for that period."""
    issuer_map = load_issuer_map(ISSUER_MAP_YAML)
    holdings = build_holdings_df(
        session, cik=cik, period_of_report=period_of_report, issuer_map=issuer_map
    )
    if holdings.empty:
        return None

    weighted = compute_weights(holdings)
    tickers = cast(pd.Series, weighted["ticker"]).dropna().astype(str).unique().tolist()
    weights_by_ticker: dict[str, float] = {}
    for _, row in weighted.iterrows():
        tkr = row["ticker"]
        if tkr is None:
            continue
        if isinstance(tkr, float) and (tkr != tkr):  # NaN check (NaN != NaN)
            continue
        key = str(tkr)
        weights_by_ticker[key] = weights_by_ticker.get(key, 0.0) + float(cast(float, row["weight"]))
    weights = pd.Series(weights_by_ticker, dtype=float)

    prices, missing = _load_prices_wide(session, tickers, period_of_report, RETURN_WINDOW_DAYS)
    prices_empty = bool(getattr(prices, "empty", True))
    if prices_empty:
        return ClusterResult(
            fund_cik=cik,
            quarter_period=period_of_report,
            rho_threshold=rho_threshold,
            min_weight=min_weight,
            clusters=[],
            missing_tickers=missing,
            insufficient=True,
        )

    clusters = correlation_clusters(
        prices,
        weights,
        rho_threshold=rho_threshold,
        min_weight=min_weight,
    )
    insufficient = len(prices) < RETURN_WINDOW_DAYS // 2
    return ClusterResult(
        fund_cik=cik,
        quarter_period=period_of_report,
        rho_threshold=rho_threshold,
        min_weight=min_weight,
        clusters=clusters,
        missing_tickers=missing,
        insufficient=insufficient,
    )
