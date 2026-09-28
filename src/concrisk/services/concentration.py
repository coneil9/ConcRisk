from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
from sqlalchemy.orm import Session

from concrisk.risk import (
    compute_weights,
    effective_n,
    hhi,
    largest_issuer_weight,
    load_issuer_map,
    sector_weights,
    top_n_weight,
)
from concrisk.services.funds import list_available_periods
from concrisk.services.holdings import build_holdings_df
from concrisk.services.quarters import format_quarter

ISSUER_MAP_YAML = Path("config/issuer_map.yaml")


@dataclass(frozen=True)
class ConcentrationSnapshot:
    fund_cik: str
    quarter: str
    as_of: date
    hhi: float
    effective_n: float
    top5: float
    top10: float
    largest_issuer: tuple[str, float]
    sector_weights: dict[str, float]


def get_concentration(
    session: Session,
    *,
    cik: str,
    period_of_report: date,
    issuer_map: dict[str, str] | None = None,
) -> ConcentrationSnapshot | None:
    """Compute the SPEC §6.1–6.4 metrics for one fund-quarter. Returns
    None if the fund has no non-superseded positions for that period."""
    if issuer_map is None:
        issuer_map = load_issuer_map(ISSUER_MAP_YAML)
    holdings = build_holdings_df(
        session, cik=cik, period_of_report=period_of_report, issuer_map=issuer_map
    )
    if holdings.empty:
        return None
    weighted = compute_weights(holdings)
    weights = cast(pd.Series, weighted["weight"])
    issuer_key, issuer_weight = largest_issuer_weight(weighted)
    return ConcentrationSnapshot(
        fund_cik=cik,
        quarter=format_quarter(period_of_report),
        as_of=period_of_report,
        hhi=hhi(weights),
        effective_n=effective_n(weights),
        top5=top_n_weight(weights, 5),
        top10=top_n_weight(weights, 10),
        largest_issuer=(issuer_key, issuer_weight),
        sector_weights={str(k): float(v) for k, v in sector_weights(weighted).items()},
    )


def get_concentration_history(session: Session, *, cik: str) -> list[dict[str, Any]]:
    """One entry per available quarter: {quarter, as_of, hhi, top10}.
    SPEC §8 concentration/history shape."""
    periods = list_available_periods(session, cik)
    if not periods:
        return []
    issuer_map = load_issuer_map(ISSUER_MAP_YAML)
    out: list[dict[str, Any]] = []
    for p in periods:
        snap = get_concentration(session, cik=cik, period_of_report=p, issuer_map=issuer_map)
        if snap is None:
            continue
        out.append(
            {
                "quarter": snap.quarter,
                "as_of": snap.as_of,
                "hhi": snap.hhi,
                "top10": snap.top10,
            }
        )
    return out
