from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
from sqlalchemy.orm import Session

from concrisk.risk import (
    Breach,
    compute_weights,
    effective_n,
    evaluate_limits,
    hhi,
    issuer_weights,
    load_issuer_map,
    load_limits,
    sector_weights,
)
from concrisk.services.funds import latest_period_for_fund, list_tracked_funds
from concrisk.services.holdings import build_holdings_df
from concrisk.services.quarters import format_quarter

LIMITS_YAML = Path("limits.yaml")
ISSUER_MAP_YAML = Path("config/issuer_map.yaml")


def breaches_for_quarter(
    session: Session,
    *,
    period_of_report: date | None = None,
    severity: str | None = None,
) -> list[Breach]:
    """Evaluate limits.yaml against every tracked fund. If period_of_report
    is None, each fund uses its own latest available quarter. `severity`
    filters the result to 'warning' or 'breach'."""
    config = load_limits(LIMITS_YAML)
    issuer_map = load_issuer_map(ISSUER_MAP_YAML)

    out: list[Breach] = []
    for cik, _ in list_tracked_funds():
        period = period_of_report or latest_period_for_fund(session, cik)
        if period is None:
            continue
        holdings = build_holdings_df(
            session, cik=cik, period_of_report=period, issuer_map=issuer_map
        )
        if holdings.empty:
            continue
        weighted = compute_weights(holdings)
        weights = cast(pd.Series, weighted["weight"])
        breaches = evaluate_limits(
            config,
            fund_cik=cik,
            quarter=format_quarter(period),
            weights=weights,
            issuer_wts=issuer_weights(weighted),
            sector_wts=sector_weights(weighted),
            hhi_value=hhi(weights),
            effective_n_value=effective_n(weights),
        )
        out.extend(breaches)

    if severity:
        out = [b for b in out if b.severity == severity]
    return out
