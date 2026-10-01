from typing import Literal, cast

import pandas as pd

Scenario = Literal["notional", "atm", "ignore"]

# SPEC §6.5: delta assumptions per scenario.
DELTAS: dict[str, dict[str, float]] = {
    "notional": {"CALL": 1.0, "PUT": -1.0},
    "atm": {"CALL": 0.5, "PUT": -0.5},
    "ignore": {"CALL": 0.0, "PUT": 0.0},
}


def _delta(scenario: str, put_call: str | None) -> float:
    if put_call is None:
        return 0.0
    return DELTAS[scenario].get(put_call.upper(), 0.0)


def combined_issuer_exposure(
    holdings: pd.DataFrame,
    scenario: Scenario = "atm",
    *,
    issuer_col: str = "issuer_key",
    value_col: str = "value_usd",
    put_call_col: str = "put_call",
) -> pd.DataFrame:
    """Combined issuer exposure under one options scenario (SPEC §6.5).

    Returns a DataFrame with columns:
      - issuer_key
      - equity_value_usd   (sum of equity-row values per issuer)
      - option_delta_value (sum of δ × U_option per issuer, signed)
      - equity_weight      (equity_value / equity_NAV)
      - combined_weight    ((equity + option_delta) / equity_NAV)

    equity_NAV is the sum of all equity (non-option) rows. Combined
    weight can exceed 1 when options stack onto equity (long calls)
    or go negative (long puts). Downstream formatters show the scenario
    name alongside — per SPEC §6.5 ("every API response ... states the
    scenario").
    """
    if scenario not in DELTAS:
        raise ValueError(f"unknown scenario: {scenario!r} (expected notional/atm/ignore)")
    if issuer_col not in holdings.columns:
        raise ValueError(f"holdings missing {issuer_col!r} column")

    df = holdings.copy()
    put_call = cast(pd.Series, df[put_call_col]) if put_call_col in df.columns else None
    is_equity = put_call.isna() if put_call is not None else pd.Series(True, index=df.index)

    df["_delta"] = [
        _delta(scenario, pc)
        for pc in (
            cast(pd.Series, df[put_call_col]).tolist()
            if put_call is not None
            else [None] * len(df)
        )
    ]
    df["_signed_value"] = cast(pd.Series, df[value_col]).astype(float) * df["_delta"]

    equity_nav = float(cast(pd.Series, df.loc[is_equity, value_col]).astype(float).sum())
    if equity_nav <= 0:
        return pd.DataFrame(
            columns=[
                "issuer_key",
                "equity_value_usd",
                "option_delta_value",
                "equity_weight",
                "combined_weight",
            ]
        )

    equity_df = df.loc[is_equity].copy()
    option_df = df.loc[~is_equity].copy() if put_call is not None else df.iloc[0:0]

    equity_by_issuer = cast(
        pd.Series,
        equity_df.groupby(issuer_col)[value_col].sum().astype(float),
    )
    if not option_df.empty:
        option_by_issuer = cast(
            pd.Series,
            option_df.groupby(issuer_col)["_signed_value"].sum().astype(float),
        )
    else:
        option_by_issuer = pd.Series(dtype=float)

    issuers = sorted(set(equity_by_issuer.index) | set(option_by_issuer.index))
    rows = []
    for issuer in issuers:
        eq = float(equity_by_issuer.get(issuer, 0.0) or 0.0)
        opt = float(option_by_issuer.get(issuer, 0.0) or 0.0)
        rows.append(
            {
                "issuer_key": issuer,
                "equity_value_usd": eq,
                "option_delta_value": opt,
                "equity_weight": eq / equity_nav,
                "combined_weight": (eq + opt) / equity_nav,
            }
        )
    out = pd.DataFrame(rows)
    return cast(pd.DataFrame, out.sort_values("combined_weight", ascending=False))
