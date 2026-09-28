import pandas as pd
import pytest

from concrisk.risk import compute_weights


def test_weights_sum_to_one() -> None:
    # HAND-COMPUTED: values [60, 40] total 100 → weights [0.6, 0.4].
    df = pd.DataFrame(
        {
            "cusip": ["A", "B"],
            "value_usd": [60.0, 40.0],
            "put_call": [None, None],
        }
    )
    out = compute_weights(df)
    assert list(out["weight"]) == [0.6, 0.4]
    assert out["weight"].sum() == pytest.approx(1.0)


def test_weights_exclude_options_by_default() -> None:
    # HAND-COMPUTED: equity row 80, options rows dropped, total 80 → weight 1.0.
    df = pd.DataFrame(
        {
            "cusip": ["EQ", "OPT_C", "OPT_P"],
            "value_usd": [80.0, 30.0, 20.0],
            "put_call": [None, "CALL", "PUT"],
        }
    )
    out = compute_weights(df)
    assert len(out) == 1
    assert out.iloc[0]["cusip"] == "EQ"
    assert out.iloc[0]["weight"] == pytest.approx(1.0)


def test_weights_include_options_flag() -> None:
    # HAND-COMPUTED: total 130 → weights 80/130, 30/130, 20/130.
    df = pd.DataFrame(
        {
            "cusip": ["EQ", "OPT_C", "OPT_P"],
            "value_usd": [80.0, 30.0, 20.0],
            "put_call": [None, "CALL", "PUT"],
        }
    )
    out = compute_weights(df, include_options=True)
    assert len(out) == 3
    assert out["weight"].sum() == pytest.approx(1.0)
    assert out.iloc[0]["weight"] == pytest.approx(80 / 130)


def test_weights_empty_portfolio_returns_zero() -> None:
    df = pd.DataFrame({"cusip": [], "value_usd": [], "put_call": []})
    out = compute_weights(df)
    assert len(out) == 0


def test_weights_missing_value_column_raises() -> None:
    df = pd.DataFrame({"cusip": ["A"], "put_call": [None]})
    with pytest.raises(ValueError, match="value_usd"):
        compute_weights(df)
