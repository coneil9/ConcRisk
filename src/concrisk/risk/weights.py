from typing import cast

import pandas as pd


def compute_weights(
    holdings: pd.DataFrame,
    *,
    include_options: bool = False,
    value_col: str = "value_usd",
) -> pd.DataFrame:
    """Return an equity-only view of `holdings` with a `weight` column that
    sums to 1.0 across the returned rows.

    Per SPEC §6 header, weights use equity positions only. Rows with a
    non-null `put_call` are excluded unless `include_options=True`. Weight
    is a fraction (0.12), not a percentage.
    """
    if value_col not in holdings.columns:
        raise ValueError(f"holdings missing required column: {value_col!r}")

    out = holdings.copy()
    if not include_options and "put_call" in out.columns:
        mask = out["put_call"].isna()
        out = cast(pd.DataFrame, out.loc[mask].copy())

    values = cast(pd.Series, out[value_col]).astype(float)
    total = float(values.sum())
    if total <= 0:
        out["weight"] = 0.0
        return out

    out["weight"] = values / total
    return out
