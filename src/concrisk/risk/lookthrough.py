from dataclasses import dataclass
from typing import cast

import pandas as pd


@dataclass(frozen=True)
class LookthroughResult:
    weights: pd.Series  # ticker -> expanded weight (fraction)
    coverage: float  # fraction of ETF weight that was expanded


def apply_lookthrough(
    weighted_holdings: pd.DataFrame,
    etf_constituents: dict[str, list[tuple[str, float]]],
    *,
    ticker_col: str = "ticker",
    weight_col: str = "weight",
    is_etf_col: str = "is_etf",
) -> LookthroughResult:
    """SPEC §6.6: expand ETF positions into underlying holdings.

    `etf_constituents[etf_ticker]` is a list of (underlying_ticker, weight)
    tuples where the sum of weights is approximately 1 (ETF holdings
    expressed as fractions of the ETF).

    Returns:
      - weights: Series indexed by ticker with expanded weights.
        Direct position weight + Σ_e w_e × c_{e,j}.
      - coverage: fraction of ETF weight that had constituent data;
        1.0 means every ETF was expanded, 0.0 means none were.
        Called `lookthrough_coverage` in API responses.

    Hand-check (from SPEC): fund = 90% AAPL direct + 10% SPY;
    SPY constituents = {AAPL: 0.07, ...}. Expanded AAPL weight =
    0.90 + 0.10 × 0.07 = 0.907.
    """
    weights = cast(pd.Series, weighted_holdings[weight_col]).astype(float)
    tickers = cast(pd.Series, weighted_holdings[ticker_col])
    is_etf = (
        cast(pd.Series, weighted_holdings[is_etf_col]).astype(bool)
        if is_etf_col in weighted_holdings.columns
        else pd.Series(False, index=weighted_holdings.index)
    )

    expanded: dict[str, float] = {}

    etf_weight_total = 0.0
    etf_weight_expanded = 0.0

    for idx in weighted_holdings.index:
        tkr = tickers.loc[idx]
        w = float(weights.loc[idx])
        if pd.isna(tkr) or not tkr:
            continue
        tkr_str = str(tkr).upper()

        if is_etf.loc[idx]:
            etf_weight_total += w
            constituents = etf_constituents.get(tkr_str)
            if constituents is None:
                # No constituent data — ETF stays as a single line.
                expanded[tkr_str] = expanded.get(tkr_str, 0.0) + w
                continue
            etf_weight_expanded += w
            for underlying_ticker, c_weight in constituents:
                u = underlying_ticker.upper()
                expanded[u] = expanded.get(u, 0.0) + w * float(c_weight)
        else:
            expanded[tkr_str] = expanded.get(tkr_str, 0.0) + w

    coverage = 1.0 if etf_weight_total == 0 else etf_weight_expanded / etf_weight_total

    out_series = pd.Series(expanded, name="weight").sort_values(ascending=False)
    return LookthroughResult(weights=out_series, coverage=coverage)
