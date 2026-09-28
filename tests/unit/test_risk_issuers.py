from pathlib import Path

import pandas as pd

from concrisk.risk import add_issuer_key, load_issuer_map, resolve_issuer_key

MAP = {"GOOG": "GOOG", "GOOGL": "GOOG", "BRK.A": "BRK", "BRK.B": "BRK"}


def test_resolve_issuer_key_maps_share_class() -> None:
    assert resolve_issuer_key("GOOGL", "cusip_ignored", MAP) == "GOOG"
    assert resolve_issuer_key("BRK.B", "cusip_ignored", MAP) == "BRK"


def test_resolve_issuer_key_unmapped_ticker_returns_itself() -> None:
    assert resolve_issuer_key("AAPL", "037833100", MAP) == "AAPL"


def test_resolve_issuer_key_missing_ticker_falls_back_to_cusip() -> None:
    # OpenFIGI didn't resolve — CUSIP keeps the row in aggregation.
    assert resolve_issuer_key(None, "999999999", MAP) == "999999999"
    assert resolve_issuer_key("", "999999999", MAP) == "999999999"


def test_add_issuer_key_annotates_dataframe() -> None:
    df = pd.DataFrame(
        {
            "cusip": ["c1", "c2", "c3", "c4"],
            "ticker": ["GOOG", "GOOGL", "AAPL", None],
        }
    )
    out = add_issuer_key(df, MAP)
    assert list(out["issuer_key"]) == ["GOOG", "GOOG", "AAPL", "c4"]


def test_load_issuer_map_reads_yaml() -> None:
    # Real project map: verify a couple of well-known rollups.
    m = load_issuer_map(Path("config/issuer_map.yaml"))
    assert m["GOOGL"] == "GOOG"
    assert m["BRK.B"] == "BRK"
