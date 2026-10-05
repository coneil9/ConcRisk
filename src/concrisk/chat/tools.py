import math
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
from sqlalchemy.orm import Session

from concrisk.chat.resolve import (
    AmbiguousFund,
    ResolvedFund,
    UnknownFund,
    resolve_fund_ref,
)
from concrisk.risk import compute_weights, load_issuer_map
from concrisk.services import (
    breaches_for_quarter,
    build_holdings_df,
    format_quarter,
    get_clusters,
    get_concentration,
    get_concentration_history,
    issuer_exposure_across_funds,
    latest_period_for_fund,
    list_funds_with_latest_quarter,
    parse_quarter,
)

ISSUER_MAP_YAML = Path("config/issuer_map.yaml")

# --- data_notes vocabulary ---
NOTE_QUARTERLY_STALE = (
    "13F is quarterly and filed up to 45 days after quarter end — "
    "holdings may be up to ~135 days stale"
)
NOTE_LONG_ONLY = "long positions only; 13F does not report shorts"
NOTE_SECTOR_PENDING = "sector data not yet populated (Phase 7); positions may show Unclassified"
NOTE_OPTIONS_EXCLUDED = "options positions excluded from weights"

# --- Anthropic tool schemas (SPEC §10, 1:1 with services) ---

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_funds",
        "description": (
            "List every tracked fund with its latest available quarter (or null if never loaded)."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_concentration",
        "description": (
            "Return HHI, effective N, top5, top10, largest issuer, and sector "
            "weights for one fund-quarter. Pass options_scenario to also get "
            "per-issuer combined (equity + delta × option) exposure. Pass "
            "lookthrough=true to also get ETF-expanded weights."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fund": {
                    "type": "string",
                    "description": "CIK (any padding) or fund name (fuzzy match).",
                },
                "quarter": {
                    "type": "string",
                    "description": "e.g. '2026Q1'; omit for latest available.",
                },
                "options_scenario": {
                    "type": "string",
                    "enum": ["notional", "atm", "ignore"],
                    "description": (
                        "Delta scenario for options exposure. atm = CALL +0.5 / "
                        "PUT -0.5; notional = ±1.0; ignore = 0."
                    ),
                },
                "lookthrough": {
                    "type": "boolean",
                    "description": "Expand ETF positions via etf_constituents.",
                },
            },
            "required": ["fund"],
        },
    },
    {
        "name": "get_holdings",
        "description": (
            "Return positions with weights for one fund-quarter, sorted descending by weight."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fund": {"type": "string"},
                "quarter": {"type": "string"},
                "top": {
                    "type": "integer",
                    "description": "return only the top N (0 or omit for all).",
                },
            },
            "required": ["fund"],
        },
    },
    {
        "name": "get_exposure",
        "description": (
            "For a given ticker, return every tracked fund that holds it "
            "(rolled up by issuer_key so GOOG/GOOGL sum together). Pass "
            "lookthrough=true to also include weight via ETF holdings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "quarter": {"type": "string"},
                "lookthrough": {
                    "type": "boolean",
                    "description": "Also expand ETF positions.",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_breaches",
        "description": (
            "Return concentration-limit breaches across every tracked fund. "
            "Optionally filter by severity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "quarter": {"type": "string"},
                "severity": {"type": "string", "enum": ["warning", "breach"]},
            },
        },
    },
    {
        "name": "compare_funds",
        "description": "Concentration snapshots for two or more funds side by side.",
        "input_schema": {
            "type": "object",
            "properties": {
                "funds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
                "quarter": {"type": "string"},
            },
            "required": ["funds"],
        },
    },
    {
        "name": "get_concentration_history",
        "description": "Per-quarter HHI and top10 for one fund, sorted ascending.",
        "input_schema": {
            "type": "object",
            "properties": {"fund": {"type": "string"}},
            "required": ["fund"],
        },
    },
    {
        "name": "get_correlation_clusters",
        "description": (
            "Return correlation clusters for a fund-quarter. Groups holdings "
            "whose daily log returns correlate at or above the threshold — "
            "flags 'hidden concentration' across different issuers that "
            "move together. Requires price history (yfinance backfill)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fund": {"type": "string"},
                "quarter": {"type": "string"},
                "rho_threshold": {
                    "type": "number",
                    "description": "Minimum pairwise correlation; default 0.7.",
                },
                "min_weight": {
                    "type": "number",
                    "description": "Weight floor for inclusion; default 0.005 (0.5%).",
                },
            },
            "required": ["fund"],
        },
    },
]


# --- helpers ---


def _none_if_na(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def _resolve(fund_ref: str) -> ResolvedFund | dict[str, Any]:
    r = resolve_fund_ref(fund_ref)
    if isinstance(r, UnknownFund):
        return {
            "error": "unknown_fund",
            "hint": "call list_funds to see tracked funds",
        }
    if isinstance(r, AmbiguousFund):
        return {
            "error": "ambiguous_fund",
            "candidates": [{"cik": c.cik, "name": c.name} for c in r.candidates],
        }
    return r


def _parse_quarter_arg(quarter: str | None) -> date | None:
    if not quarter:
        return None
    return parse_quarter(quarter)


def _resolve_period(
    session: Session, fund: ResolvedFund, quarter_arg: str | None
) -> date | dict[str, Any]:
    q = _parse_quarter_arg(quarter_arg)
    if q is not None:
        return q
    latest = latest_period_for_fund(session, fund.cik)
    if latest is None:
        return {"error": "no_data", "detail": f"no filings loaded for {fund.name}"}
    return latest


# --- Handlers ---


def _tool_list_funds(_args: dict[str, Any], session: Session) -> dict[str, Any]:
    summaries = list_funds_with_latest_quarter(session)
    return {
        "funds": [
            {
                "cik": s.cik,
                "name": s.name,
                "latest_quarter": (
                    format_quarter(s.latest_quarter_date) if s.latest_quarter_date else None
                ),
            }
            for s in summaries
        ],
        "data_notes": [NOTE_QUARTERLY_STALE],
    }


def _tool_get_concentration(args: dict[str, Any], session: Session) -> dict[str, Any]:
    r = _resolve(args["fund"])
    if isinstance(r, dict):
        return r
    period = _resolve_period(session, r, args.get("quarter"))
    if isinstance(period, dict):
        return period
    options_scenario = args.get("options_scenario")
    lookthrough = bool(args.get("lookthrough", False))
    snap = get_concentration(
        session,
        cik=r.cik,
        period_of_report=period,
        options_scenario=options_scenario,
        lookthrough=lookthrough,
    )
    if snap is None:
        return {"error": "no_data", "detail": f"no holdings for {r.name} at {period}"}
    notes = [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY, NOTE_SECTOR_PENDING]
    if options_scenario is None:
        notes.insert(2, NOTE_OPTIONS_EXCLUDED)
    out: dict[str, Any] = {
        "fund_cik": r.cik,
        "fund_name": r.name,
        "quarter": snap.quarter,
        "hhi": snap.hhi,
        "effective_n": snap.effective_n,
        "top5": snap.top5,
        "top10": snap.top10,
        "largest_issuer": {
            "issuer_key": snap.largest_issuer[0],
            "weight": snap.largest_issuer[1],
        },
        "sector_weights": snap.sector_weights,
        "data_notes": notes,
    }
    if options_scenario is not None:
        out["options_scenario"] = options_scenario
        out["combined_issuers"] = [
            {
                "issuer_key": c.issuer_key,
                "equity_weight": c.equity_weight,
                "option_delta_weight": c.option_delta_weight,
                "combined_weight": c.combined_weight,
            }
            for c in snap.combined_issuers[:20]
        ]
    if lookthrough:
        out["lookthrough_coverage"] = snap.lookthrough_coverage
        # Keep response bounded — top 25 by weight.
        top = sorted(snap.lookthrough_weights.items(), key=lambda kv: -kv[1])[:25]
        out["lookthrough_weights"] = {k: v for k, v in top}
    return out


def _tool_get_holdings(args: dict[str, Any], session: Session) -> dict[str, Any]:
    r = _resolve(args["fund"])
    if isinstance(r, dict):
        return r
    period = _resolve_period(session, r, args.get("quarter"))
    if isinstance(period, dict):
        return period
    issuer_map = load_issuer_map(ISSUER_MAP_YAML)
    holdings = build_holdings_df(session, cik=r.cik, period_of_report=period, issuer_map=issuer_map)
    if holdings.empty:
        return {"error": "no_data"}
    weighted = cast(
        pd.DataFrame,
        compute_weights(holdings).sort_values("weight", ascending=False),
    )
    top = args.get("top") or 0
    if top:
        weighted = cast(pd.DataFrame, weighted.head(top))

    cusips = cast(pd.Series, weighted["cusip"]).astype(str).tolist()
    tickers = cast(pd.Series, weighted["ticker"]).tolist()
    names = cast(pd.Series, weighted["name"]).tolist()
    sectors = cast(pd.Series, weighted["sector"]).tolist()
    put_calls = cast(pd.Series, weighted["put_call"]).tolist()
    shares_list = cast(pd.Series, weighted["shares"]).astype(float).tolist()
    values = cast(pd.Series, weighted["value_usd"]).astype(float).tolist()
    weights_list = cast(pd.Series, weighted["weight"]).astype(float).tolist()

    rows = [
        {
            "cusip": cusip,
            "ticker": _none_if_na(ticker),
            "name": _none_if_na(name),
            "sector": _none_if_na(sector),
            "shares": shares,
            "value_usd": value,
            "weight": weight,
            "put_call": _none_if_na(pc),
        }
        for cusip, ticker, name, sector, pc, shares, value, weight in zip(
            cusips,
            tickers,
            names,
            sectors,
            put_calls,
            shares_list,
            values,
            weights_list,
            strict=True,
        )
    ]
    return {
        "fund_cik": r.cik,
        "fund_name": r.name,
        "quarter": format_quarter(period),
        "holdings": rows,
        "data_notes": [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY, NOTE_OPTIONS_EXCLUDED],
    }


def _tool_get_exposure(args: dict[str, Any], session: Session) -> dict[str, Any]:
    ticker = args["ticker"]
    quarter = _parse_quarter_arg(args.get("quarter"))
    lookthrough = bool(args.get("lookthrough", False))
    rows = issuer_exposure_across_funds(
        session, ticker=ticker, period_of_report=quarter, lookthrough=lookthrough
    )
    if not rows:
        return {"error": "no_data", "detail": f"no tracked fund holds {ticker.upper()}"}
    return {
        "ticker": ticker.upper(),
        "lookthrough": lookthrough,
        "exposures": [
            {
                "fund_cik": e.fund_cik,
                "fund_name": e.fund_name,
                "quarter": e.quarter,
                "weight": e.weight,
                "value_usd": e.value_usd,
                "ticker": e.ticker,
                "issuer_key": e.issuer_key,
                "lookthrough_weight": e.lookthrough_weight,
                "lookthrough_coverage": e.lookthrough_coverage,
            }
            for e in rows
        ],
        "data_notes": [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY, NOTE_OPTIONS_EXCLUDED],
    }


def _tool_get_breaches(args: dict[str, Any], session: Session) -> dict[str, Any]:
    quarter = _parse_quarter_arg(args.get("quarter"))
    severity = args.get("severity")
    breaches = breaches_for_quarter(session, period_of_report=quarter, severity=severity)
    return {
        "breaches": [
            {
                "fund_cik": b.fund_cik,
                "quarter": b.quarter,
                "rule_id": b.rule_id,
                "metric": b.metric,
                "observed": b.observed,
                "threshold": b.threshold,
                "severity": b.severity,
                "scope_key": b.scope_key,
            }
            for b in breaches
        ],
        "data_notes": [
            NOTE_QUARTERLY_STALE,
            NOTE_LONG_ONLY,
            NOTE_OPTIONS_EXCLUDED,
            NOTE_SECTOR_PENDING,
        ],
    }


def _tool_compare_funds(args: dict[str, Any], session: Session) -> dict[str, Any]:
    fund_refs = args["funds"]
    if len(fund_refs) < 2:
        return {"error": "need_at_least_two_funds"}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for ref in fund_refs:
        r = _resolve(ref)
        if isinstance(r, dict):
            errors.append({"fund_input": ref, **r})
            continue
        period = _resolve_period(session, r, args.get("quarter"))
        if isinstance(period, dict):
            errors.append({"fund_input": ref, **period})
            continue
        snap = get_concentration(session, cik=r.cik, period_of_report=period)
        if snap is None:
            errors.append({"fund_input": ref, "error": "no_data"})
            continue
        results.append(
            {
                "fund_cik": r.cik,
                "fund_name": r.name,
                "quarter": snap.quarter,
                "hhi": snap.hhi,
                "effective_n": snap.effective_n,
                "top5": snap.top5,
                "top10": snap.top10,
                "largest_issuer": {
                    "issuer_key": snap.largest_issuer[0],
                    "weight": snap.largest_issuer[1],
                },
            }
        )
    return {
        "funds": results,
        "errors": errors,
        "data_notes": [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY, NOTE_OPTIONS_EXCLUDED],
    }


def _tool_get_concentration_history(args: dict[str, Any], session: Session) -> dict[str, Any]:
    r = _resolve(args["fund"])
    if isinstance(r, dict):
        return r
    rows = get_concentration_history(session, cik=r.cik)
    return {
        "fund_cik": r.cik,
        "fund_name": r.name,
        "history": [
            {"quarter": row["quarter"], "hhi": row["hhi"], "top10": row["top10"]} for row in rows
        ],
        "data_notes": [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY],
    }


def _tool_get_correlation_clusters(
    args: dict[str, Any], session: Session
) -> dict[str, Any]:
    r = _resolve(args["fund"])
    if isinstance(r, dict):
        return r
    period = _resolve_period(session, r, args.get("quarter"))
    if isinstance(period, dict):
        return period
    rho = float(args.get("rho_threshold", 0.7))
    mw = float(args.get("min_weight", 0.005))
    result = get_clusters(
        session, cik=r.cik, period_of_report=period, rho_threshold=rho, min_weight=mw
    )
    if result is None:
        return {"error": "no_data", "detail": f"no holdings for {r.name} at {period}"}
    notes = [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY]
    if result.insufficient:
        notes.append("insufficient price history for a reliable correlation window")
    if result.missing_tickers:
        notes.append(
            f"{len(result.missing_tickers)} ticker(s) excluded for missing prices"
        )
    return {
        "fund_cik": r.cik,
        "fund_name": r.name,
        "quarter": format_quarter(period),
        "rho_threshold": rho,
        "min_weight": mw,
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "tickers": list(c.tickers),
                "weight": c.weight,
                "avg_correlation": c.avg_correlation,
            }
            for c in result.clusters
        ],
        "missing_tickers": result.missing_tickers,
        "insufficient_price_data": result.insufficient,
        "data_notes": notes,
    }


_HANDLERS = {
    "list_funds": _tool_list_funds,
    "get_concentration": _tool_get_concentration,
    "get_holdings": _tool_get_holdings,
    "get_exposure": _tool_get_exposure,
    "get_breaches": _tool_get_breaches,
    "compare_funds": _tool_compare_funds,
    "get_concentration_history": _tool_get_concentration_history,
    "get_correlation_clusters": _tool_get_correlation_clusters,
}


def execute_tool(name: str, arguments: dict[str, Any], session: Session) -> dict[str, Any]:
    """Dispatch one tool call. Returns a JSON-serializable dict — always,
    even on error, so the agent loop can hand it back to the model."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": "unknown_tool", "name": name}
    try:
        return handler(arguments, session)
    except Exception as e:
        return {"error": "tool_exception", "detail": str(e)}
