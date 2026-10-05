"""Correlation clusters per SPEC §6.7.

Daily log returns over N trading days → correlation matrix → distance
matrix `d = √(0.5 · (1 − ρ))` → scipy average-linkage hierarchical
clustering → clusters cut at `ρ ≥ rho_threshold`.

Flags "hidden concentration" across different issuers that happen to
move together.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import cast

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


@dataclass(frozen=True)
class Cluster:
    cluster_id: int
    tickers: tuple[str, ...]
    weight: float  # sum of input weights across cluster members
    avg_correlation: float


def _log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """index=date, columns=ticker, values=close → log returns, NaNs dropped."""
    closes = cast(pd.DataFrame, prices.astype(float))
    log_prices = cast(pd.DataFrame, np.log(closes))
    returns = cast(pd.DataFrame, log_prices.diff().dropna(how="all"))
    return cast(pd.DataFrame, returns.dropna(axis=1, how="any"))


def correlation_clusters(
    prices: pd.DataFrame,
    weights: pd.Series,
    *,
    rho_threshold: float = 0.7,
    min_weight: float = 0.005,
) -> list[Cluster]:
    """Returns clusters whose members have pairwise correlation ≥ `rho_threshold`.

    Inputs:
      - prices: wide DataFrame index=date, columns=ticker, close prices.
      - weights: Series indexed by ticker (same tickers as prices columns),
        values = fraction of portfolio.
      - rho_threshold: minimum pairwise correlation to be in the same
        cluster (default 0.7, per SPEC §6.7).
      - min_weight: holdings below this weight are excluded from the
        clustering (default 0.5%, per SPEC §6.7).

    Returns only clusters with ≥ 2 members. Singletons are not useful.
    """
    # Filter weights by min threshold.
    wts = cast(pd.Series, weights.astype(float))
    kept = cast(pd.Series, wts[wts >= min_weight])
    if len(kept) < 2:
        return []
    # Line up prices with the kept tickers that actually have columns.
    tickers = [t for t in kept.index if t in prices.columns]
    if len(tickers) < 2:
        return []
    sub_prices = cast(pd.DataFrame, prices[tickers])

    returns = _log_returns(sub_prices)
    if returns.empty or returns.shape[1] < 2:
        return []

    corr = cast(pd.DataFrame, returns.corr())
    # Distance matrix per SPEC: d = sqrt(0.5 * (1 - rho)).
    raw = cast(pd.DataFrame, 0.5 * (1 - corr))
    distances = raw.clip(lower=0).to_numpy()
    np.fill_diagonal(distances, 0.0)
    distances = np.sqrt(distances)
    # Scipy wants a condensed (upper-triangle) distance vector.
    condensed = squareform(distances, checks=False)
    linkage_matrix = linkage(condensed, method="average")
    cut_distance = sqrt(0.5 * (1 - rho_threshold))
    assignments = fcluster(linkage_matrix, t=cut_distance, criterion="distance")

    tickers_in_corr: list[str] = [str(t) for t in corr.columns]
    corr_values = corr.to_numpy()

    buckets: dict[int, list[int]] = {}
    for i, cid in enumerate(assignments):
        buckets.setdefault(int(cid), []).append(i)

    clusters: list[Cluster] = []
    for cid, idxs in buckets.items():
        if len(idxs) < 2:
            continue
        members = tuple(tickers_in_corr[i] for i in idxs)
        total_weight = float(sum(float(cast(float, kept[t])) for t in members))
        pair_vals: list[float] = []
        for a in idxs:
            for b in idxs:
                if a < b:
                    pair_vals.append(float(corr_values[a, b]))
        avg_corr = sum(pair_vals) / len(pair_vals) if pair_vals else 1.0
        clusters.append(
            Cluster(
                cluster_id=cid,
                tickers=members,
                weight=total_weight,
                avg_correlation=avg_corr,
            )
        )
    return sorted(clusters, key=lambda c: -c.weight)
