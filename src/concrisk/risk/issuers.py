import math
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def load_issuer_map(path: Path) -> dict[str, str]:
    """Read config/issuer_map.yaml → dict of ticker → issuer_key."""
    data = yaml.safe_load(Path(path).read_text())
    mapping = data.get("issuer_map") if isinstance(data, dict) else None
    return dict(mapping or {})


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def resolve_issuer_key(
    ticker: str | None,
    cusip: str,
    mapping: dict[str, str],
) -> str:
    """Ticker rollup with a fallback chain: mapping[ticker] → ticker → cusip.

    Missing ticker (OpenFIGI couldn't resolve the CUSIP; empty string;
    or a pandas NaN when reading from a DataFrame) → use the CUSIP itself
    so the row still participates in aggregation instead of being silently
    dropped.
    """
    if _is_missing(ticker):
        return cusip
    assert ticker is not None
    return mapping.get(ticker, ticker)


def add_issuer_key(
    holdings: pd.DataFrame,
    mapping: dict[str, str],
    *,
    ticker_col: str = "ticker",
    cusip_col: str = "cusip",
) -> pd.DataFrame:
    """Add an `issuer_key` column to a copy of `holdings`."""
    out = holdings.copy()
    out["issuer_key"] = [
        resolve_issuer_key(t, c, mapping)
        for t, c in zip(out[ticker_col], out[cusip_col], strict=True)
    ]
    return out
