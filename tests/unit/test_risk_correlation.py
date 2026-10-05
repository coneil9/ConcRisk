from datetime import date

import numpy as np
import pandas as pd
import pytest

from concrisk.risk.correlation import correlation_clusters


def _synthetic_prices(returns: dict[str, np.ndarray], days: int) -> pd.DataFrame:
    """Build a wide prices DataFrame from predetermined log-return series."""
    rng = pd.date_range(end=date(2026, 3, 31), periods=days + 1, freq="B")
    data = {}
    for ticker, r in returns.items():
        # starting price 100, cumulative log return
        data[ticker] = 100 * np.exp(np.cumsum(np.concatenate([[0.0], r])))
    return pd.DataFrame(data, index=rng)


def test_correlated_pair_clusters_together() -> None:
    # HAND-COMPUTED: three tickers over 60 trading days.
    # A and B share the SAME base random return series (corr ≈ 1).
    # C has an INDEPENDENT series (corr with A/B ≈ 0).
    # Threshold rho=0.7 should pull {A, B} into one cluster and leave C
    # as a singleton (which the function filters out — only clusters
    # with ≥ 2 members are returned).
    np.random.seed(42)
    n = 60
    shared = np.random.normal(0, 0.02, n)
    independent = np.random.normal(0, 0.02, n)
    prices = _synthetic_prices({"A": shared, "B": shared, "C": independent}, n)
    weights = pd.Series({"A": 0.4, "B": 0.3, "C": 0.3})

    clusters = correlation_clusters(prices, weights, rho_threshold=0.7)

    assert len(clusters) == 1
    c = clusters[0]
    assert set(c.tickers) == {"A", "B"}
    assert c.weight == pytest.approx(0.7)
    assert c.avg_correlation > 0.99


def test_weight_floor_excludes_small_positions() -> None:
    # HAND-COMPUTED: A and B are perfectly correlated at ρ≈1 but B is
    # below the 0.5% floor, so it gets excluded entirely → zero clusters
    # (A is left alone, singletons dropped).
    np.random.seed(1)
    shared = np.random.normal(0, 0.02, 60)
    prices = _synthetic_prices({"A": shared, "B": shared}, 60)
    weights = pd.Series({"A": 0.1, "B": 0.001})

    assert correlation_clusters(prices, weights, min_weight=0.005) == []


def test_empty_portfolio_returns_empty() -> None:
    assert correlation_clusters(pd.DataFrame(), pd.Series(dtype=float)) == []


def test_single_ticker_returns_empty() -> None:
    prices = pd.DataFrame(
        {"A": [100.0, 101.0, 102.0]},
        index=pd.date_range(end=date(2026, 3, 31), periods=3, freq="D"),
    )
    assert correlation_clusters(prices, pd.Series({"A": 1.0})) == []


def test_threshold_affects_grouping() -> None:
    # HAND-COMPUTED: A and B correlated at ~0.8 (same series + noise).
    # At rho_threshold=0.7 they cluster; at 0.9 they don't.
    np.random.seed(7)
    base = np.random.normal(0, 0.02, 80)
    noise = np.random.normal(0, 0.015, 80)
    prices = _synthetic_prices({"A": base, "B": base + 0.5 * noise}, 80)
    weights = pd.Series({"A": 0.5, "B": 0.5})

    permissive = correlation_clusters(prices, weights, rho_threshold=0.7)
    strict = correlation_clusters(prices, weights, rho_threshold=0.99)

    assert len(permissive) == 1
    assert set(permissive[0].tickers) == {"A", "B"}
    assert strict == []
