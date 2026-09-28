import pandas as pd
import pytest

from concrisk.risk import (
    UNCLASSIFIED,
    effective_n,
    hhi,
    issuer_weights,
    largest_issuer_weight,
    sector_weights,
    top_n_weight,
)


def test_hhi_spec_worked_example() -> None:
    # HAND-COMPUTED (SPEC §6.3):
    # w = (0.5, 0.3, 0.2)
    # HHI = 0.5² + 0.3² + 0.2² = 0.25 + 0.09 + 0.04 = 0.38
    w = pd.Series([0.5, 0.3, 0.2])
    assert hhi(w) == pytest.approx(0.38)


def test_hhi_empty_is_zero() -> None:
    assert hhi(pd.Series([], dtype=float)) == 0.0


def test_effective_n_matches_spec_worked_example() -> None:
    # HAND-COMPUTED: 1 / 0.38 = 2.6315789473...
    w = pd.Series([0.5, 0.3, 0.2])
    assert effective_n(w) == pytest.approx(1 / 0.38)


def test_effective_n_of_single_position_equals_one() -> None:
    # HAND-COMPUTED: 1 / 1² = 1.
    assert effective_n(pd.Series([1.0])) == pytest.approx(1.0)


def test_top_n_weight() -> None:
    # HAND-COMPUTED: sorted [0.30, 0.20, 0.15, 0.10, 0.08, 0.05, 0.05,
    # 0.03, 0.02, 0.02]. top5 = 0.30+0.20+0.15+0.10+0.08 = 0.83.
    w = pd.Series([0.05, 0.20, 0.10, 0.08, 0.15, 0.30, 0.05, 0.03, 0.02, 0.02])
    assert top_n_weight(w, 5) == pytest.approx(0.83)


def test_top_n_saturates_at_series_length() -> None:
    w = pd.Series([0.6, 0.4])
    assert top_n_weight(w, 10) == pytest.approx(1.0)


def _mini_df() -> pd.DataFrame:
    # HAND-COMPUTED: total value 100 → weights [0.05, 0.04, 0.03, ...] etc.
    # After issuer rollup: GOOG = 0.05 + 0.04 = 0.09; AAPL = 0.03; MSFT = 0.02.
    return pd.DataFrame(
        {
            "cusip": ["c1", "c2", "c3", "c4"],
            "ticker": ["GOOG", "GOOGL", "AAPL", "MSFT"],
            "issuer_key": ["GOOG", "GOOG", "AAPL", "MSFT"],
            "sector": ["Tech", "Tech", "Tech", "Tech"],
            "weight": [0.05, 0.04, 0.03, 0.02],
        }
    )


def test_issuer_weights_rolls_up_and_sorts_desc() -> None:
    wts = issuer_weights(_mini_df())
    assert list(wts.index) == ["GOOG", "AAPL", "MSFT"]
    assert wts["GOOG"] == pytest.approx(0.09)
    assert wts["AAPL"] == pytest.approx(0.03)
    assert wts["MSFT"] == pytest.approx(0.02)


def test_largest_issuer_weight_returns_top_issuer() -> None:
    # HAND-COMPUTED: GOOG at 0.09 is the max after rollup.
    assert largest_issuer_weight(_mini_df()) == ("GOOG", pytest.approx(0.09))


def test_largest_issuer_weight_empty_returns_blank() -> None:
    empty = pd.DataFrame({"weight": [], "issuer_key": []})
    assert largest_issuer_weight(empty) == ("", 0.0)


def test_sector_weights_buckets_null_into_unclassified() -> None:
    # HAND-COMPUTED: {Tech: 0.6, Financials: 0.3, None: 0.1}
    # → Tech 0.6, Financials 0.3, Unclassified 0.1. None dropped is
    # a bug per SPEC §6.4 — assert Unclassified is present.
    df = pd.DataFrame(
        {
            "sector": ["Tech", "Tech", "Financials", None],
            "weight": [0.3, 0.3, 0.3, 0.1],
        }
    )
    wts = sector_weights(df)
    assert wts["Tech"] == pytest.approx(0.6)
    assert wts["Financials"] == pytest.approx(0.3)
    assert wts[UNCLASSIFIED] == pytest.approx(0.1)


def test_sector_weights_treats_empty_string_as_unclassified() -> None:
    df = pd.DataFrame({"sector": ["", "Tech"], "weight": [0.4, 0.6]})
    wts = sector_weights(df)
    assert wts[UNCLASSIFIED] == pytest.approx(0.4)
