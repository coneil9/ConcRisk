import pandas as pd
import pytest

from concrisk.risk.lookthrough import apply_lookthrough


def test_spec_worked_example() -> None:
    # HAND-COMPUTED (SPEC §6.6): fund holds 90% AAPL direct + 10% SPY;
    # SPY constituents = {AAPL: 0.07, MSFT: 0.06}.
    # Expanded AAPL = 0.90 + 0.10 × 0.07 = 0.907
    # Expanded MSFT =      0.10 × 0.06 = 0.006
    # Coverage = 1.0 (SPY had constituent data).
    df = pd.DataFrame(
        {"ticker": ["AAPL", "SPY"], "weight": [0.9, 0.1], "is_etf": [False, True]}
    )
    r = apply_lookthrough(df, {"SPY": [("AAPL", 0.07), ("MSFT", 0.06)]})
    assert r.weights["AAPL"] == pytest.approx(0.907)
    assert r.weights["MSFT"] == pytest.approx(0.006)
    assert r.coverage == pytest.approx(1.0)


def test_coverage_reports_unexpanded_etf_weight() -> None:
    # HAND-COMPUTED: fund holds 50% SPY + 30% QQQ + 20% AAPL.
    # Only SPY has constituent data → coverage = 50 / (50 + 30) = 0.625.
    df = pd.DataFrame(
        {
            "ticker": ["SPY", "QQQ", "AAPL"],
            "weight": [0.5, 0.3, 0.2],
            "is_etf": [True, True, False],
        }
    )
    r = apply_lookthrough(df, {"SPY": [("AAPL", 0.07)]})
    assert r.coverage == pytest.approx(0.5 / 0.8)
    # Unexpanded QQQ stays as a line.
    assert r.weights["QQQ"] == pytest.approx(0.3)
    # Expanded AAPL = direct 0.20 + SPY-portion 0.50 × 0.07 = 0.235.
    assert r.weights["AAPL"] == pytest.approx(0.235)


def test_coverage_is_one_when_no_etfs() -> None:
    df = pd.DataFrame(
        {"ticker": ["AAPL", "MSFT"], "weight": [0.6, 0.4], "is_etf": [False, False]}
    )
    r = apply_lookthrough(df, {})
    assert r.coverage == pytest.approx(1.0)
    assert r.weights["AAPL"] == pytest.approx(0.6)


def test_missing_ticker_is_skipped() -> None:
    df = pd.DataFrame(
        {"ticker": [None, "AAPL"], "weight": [0.3, 0.7], "is_etf": [False, False]}
    )
    r = apply_lookthrough(df, {})
    assert "AAPL" in r.weights.index
    # The None-ticker row doesn't produce a bucket.
    assert len(r.weights) == 1
