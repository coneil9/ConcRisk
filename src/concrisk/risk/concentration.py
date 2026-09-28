from typing import Any, cast

import pandas as pd

UNCLASSIFIED = "Unclassified"


def hhi(weights: pd.Series) -> float:
    """Herfindahl-Hirschman Index: Σ wᵢ² (SPEC §6.3).

    Weights should already sum to 1 (see `compute_weights`). Range (1/n, 1].
    Empty input → 0.
    """
    if len(weights) == 0:
        return 0.0
    squared = cast(pd.Series, weights.astype(float)) ** 2
    return float(squared.sum())


def effective_n(weights: pd.Series) -> float:
    """Effective number of positions = 1 / HHI (SPEC §6.3)."""
    h = hhi(weights)
    if h <= 0:
        return 0.0
    return 1.0 / h


def top_n_weight(weights: pd.Series, n: int) -> float:
    """Sum of the N largest weights (SPEC §6.2). If n ≥ len(weights),
    returns the total."""
    if n <= 0 or len(weights) == 0:
        return 0.0
    sorted_desc = cast(pd.Series, weights.astype(float)).sort_values(ascending=False)
    return float(sorted_desc.head(n).sum())


def issuer_weights(
    holdings: pd.DataFrame,
    *,
    weight_col: str = "weight",
    issuer_col: str = "issuer_key",
) -> pd.Series:
    """Sum weights per issuer_key. Result sorted descending."""
    if issuer_col not in holdings.columns:
        raise ValueError(
            f"holdings missing {issuer_col!r} column; call add_issuer_key first"
        )
    grouped = cast(pd.Series, holdings.groupby(issuer_col)[weight_col].sum())
    return cast(pd.Series, grouped.sort_values(ascending=False))


def largest_issuer_weight(
    holdings: pd.DataFrame,
    *,
    weight_col: str = "weight",
    issuer_col: str = "issuer_key",
) -> tuple[str, float]:
    """(issuer_key, weight) of the largest position after issuer rollup
    (SPEC §6.2 largest single-issuer weight)."""
    wts = issuer_weights(holdings, weight_col=weight_col, issuer_col=issuer_col)
    if wts.empty:
        return ("", 0.0)
    return (str(wts.index[0]), float(wts.iloc[0]))


def _bucket_sector(x: Any) -> str:
    if pd.isna(x):
        return UNCLASSIFIED
    s = str(x).strip()
    return s or UNCLASSIFIED


def sector_weights(
    holdings: pd.DataFrame,
    *,
    weight_col: str = "weight",
    sector_col: str = "sector",
) -> pd.Series:
    """Sum weights per sector (SPEC §6.4). NULL/empty sectors bucket into
    'Unclassified' — reported, never dropped.

    Note: `securities.sector` is populated in Phase 7 (yfinance). Until
    then this function returns everything under 'Unclassified' for real
    Phase 2 data.
    """
    if sector_col not in holdings.columns:
        raise ValueError(f"holdings missing {sector_col!r} column")
    sectors = cast(pd.Series, holdings[sector_col]).apply(_bucket_sector)
    grouped = cast(
        pd.Series,
        holdings.assign(_sector=sectors).groupby("_sector")[weight_col].sum(),
    )
    return cast(pd.Series, grouped.sort_values(ascending=False))
