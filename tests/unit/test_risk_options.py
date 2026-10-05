from decimal import Decimal

import pandas as pd
import pytest

from concrisk.risk.options import DELTAS, combined_issuer_exposure


def _mini_df() -> pd.DataFrame:
    """100 shares AAPL (equity $90), 50 CALL AAPL (U=$50), 20 PUT AAPL (U=$30),
    plus 100 shares MSFT (equity $10). Issuer rollup already applied."""
    return pd.DataFrame(
        {
            "cusip": ["aapl1", "aapl2", "aapl3", "msft1"],
            "ticker": ["AAPL", "AAPL", "AAPL", "MSFT"],
            "issuer_key": ["AAPL", "AAPL", "AAPL", "MSFT"],
            "put_call": [None, "CALL", "PUT", None],
            "value_usd": [Decimal("90"), Decimal("50"), Decimal("30"), Decimal("10")],
        }
    )


def test_deltas_match_spec() -> None:
    # HAND: SPEC §6.5 — notional ±1, atm ±0.5, ignore 0.
    assert DELTAS["notional"]["CALL"] == 1.0
    assert DELTAS["notional"]["PUT"] == -1.0
    assert DELTAS["atm"]["CALL"] == 0.5
    assert DELTAS["atm"]["PUT"] == -0.5
    assert DELTAS["ignore"]["CALL"] == 0.0
    assert DELTAS["ignore"]["PUT"] == 0.0


def test_atm_scenario_combines_equity_and_options() -> None:
    # HAND-COMPUTED (atm):
    # equity NAV = 90 (AAPL) + 10 (MSFT) = 100
    # AAPL option delta value = 0.5 × 50 (CALL) + (-0.5) × 30 (PUT)
    #                         = 25 - 15 = 10
    # AAPL combined weight    = (90 + 10) / 100 = 1.00
    # AAPL equity weight      = 90 / 100 = 0.90
    # MSFT combined weight    = 10 / 100 = 0.10
    df = combined_issuer_exposure(_mini_df(), "atm")
    rows = {r["issuer_key"]: r for _, r in df.iterrows()}
    assert rows["AAPL"]["equity_weight"] == pytest.approx(0.90)
    assert rows["AAPL"]["option_delta_value"] == pytest.approx(10.0)
    assert rows["AAPL"]["combined_weight"] == pytest.approx(1.00)
    assert rows["MSFT"]["combined_weight"] == pytest.approx(0.10)


def test_notional_scenario_doubles_the_delta() -> None:
    # HAND-COMPUTED (notional):
    # AAPL option delta value = 1.0 × 50 + (-1.0) × 30 = 20
    # AAPL combined weight    = (90 + 20) / 100 = 1.10
    df = combined_issuer_exposure(_mini_df(), "notional")
    rows = {r["issuer_key"]: r for _, r in df.iterrows()}
    assert rows["AAPL"]["option_delta_value"] == pytest.approx(20.0)
    assert rows["AAPL"]["combined_weight"] == pytest.approx(1.10)


def test_ignore_scenario_zeroes_options() -> None:
    # HAND-COMPUTED (ignore): options contribute 0; combined == equity weight.
    df = combined_issuer_exposure(_mini_df(), "ignore")
    rows = {r["issuer_key"]: r for _, r in df.iterrows()}
    assert rows["AAPL"]["option_delta_value"] == pytest.approx(0.0)
    assert rows["AAPL"]["combined_weight"] == pytest.approx(0.90)


def test_unknown_scenario_raises() -> None:
    with pytest.raises(ValueError, match="unknown scenario"):
        combined_issuer_exposure(_mini_df(), "bogus")  # type: ignore[arg-type]
