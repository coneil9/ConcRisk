from pathlib import Path
from typing import Annotated, Literal, cast

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from concrisk.api.deps import none_if_na, resolve_period
from concrisk.api.schemas import (
    NOTE_LONG_ONLY,
    NOTE_OPTIONS_EXCLUDED,
    NOTE_QUARTERLY_STALE,
    NOTE_SECTOR_PENDING,
    ClusterEntry,
    ClustersResponse,
    CombinedIssuerWeight,
    ConcentrationHistoryEntry,
    ConcentrationHistoryResponse,
    ConcentrationResponse,
    FundsResponse,
    FundSummary,
    HoldingRow,
    HoldingsResponse,
    IssuerWeight,
    QuartersResponse,
)
from concrisk.db.session import get_session
from concrisk.risk import compute_weights, load_issuer_map
from concrisk.services import (
    build_holdings_df,
    format_quarter,
    get_clusters,
    get_concentration,
    get_concentration_history,
    get_fund,
    list_available_periods,
    list_funds_with_latest_quarter,
    normalize_cik,
)

router = APIRouter()

ISSUER_MAP_YAML = Path("config/issuer_map.yaml")

_STANDARD_NOTES = [NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY]


def _require_fund(session: Session, cik: str) -> None:
    if get_fund(session, cik) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown or unloaded CIK {cik}",
        )


@router.get("/funds", response_model=FundsResponse)
def list_funds(
    session: Annotated[Session, Depends(get_session)],
) -> FundsResponse:
    summaries = list_funds_with_latest_quarter(session)
    return FundsResponse(
        as_of=None,
        data_notes=_STANDARD_NOTES,
        funds=[
            FundSummary(
                cik=s.cik,
                name=s.name,
                latest_quarter=(
                    format_quarter(s.latest_quarter_date) if s.latest_quarter_date else None
                ),
            )
            for s in summaries
        ],
    )


@router.get("/funds/{cik}/quarters", response_model=QuartersResponse)
def list_quarters(
    cik: str,
    session: Annotated[Session, Depends(get_session)],
) -> QuartersResponse:
    _require_fund(session, cik)
    periods = list_available_periods(session, cik)
    return QuartersResponse(
        as_of=periods[-1] if periods else None,
        data_notes=_STANDARD_NOTES,
        fund_cik=normalize_cik(cik),
        quarters=[format_quarter(p) for p in periods],
    )


@router.get("/funds/{cik}/holdings", response_model=HoldingsResponse)
def get_holdings(
    cik: str,
    session: Annotated[Session, Depends(get_session)],
    quarter: Annotated[str | None, Query()] = None,
    top: Annotated[int, Query(ge=0)] = 0,
) -> HoldingsResponse:
    _require_fund(session, cik)
    period = resolve_period(session, cik, quarter)
    issuer_map = load_issuer_map(ISSUER_MAP_YAML)
    holdings = build_holdings_df(session, cik=cik, period_of_report=period, issuer_map=issuer_map)
    if holdings.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no holdings for CIK {cik} at {period.isoformat()}",
        )
    weighted = cast(pd.DataFrame, compute_weights(holdings).sort_values("weight", ascending=False))
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
        HoldingRow(
            cusip=cusip,
            ticker=none_if_na(ticker),
            name=none_if_na(name),
            sector=none_if_na(sector),
            shares=shares,
            value_usd=value,
            weight=weight,
            put_call=none_if_na(pc),
        )
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
    total = sum(values)
    return HoldingsResponse(
        as_of=period,
        data_notes=[*_STANDARD_NOTES, NOTE_OPTIONS_EXCLUDED],
        fund_cik=normalize_cik(cik),
        quarter=format_quarter(period),
        total_value_usd=total,
        holdings=rows,
    )


@router.get("/funds/{cik}/concentration", response_model=ConcentrationResponse)
def get_concentration_endpoint(
    cik: str,
    session: Annotated[Session, Depends(get_session)],
    quarter: Annotated[str | None, Query()] = None,
    options_scenario: Annotated[
        Literal["notional", "atm", "ignore"] | None, Query()
    ] = None,
    lookthrough: Annotated[bool, Query()] = False,
) -> ConcentrationResponse:
    _require_fund(session, cik)
    period = resolve_period(session, cik, quarter)
    snap = get_concentration(
        session,
        cik=cik,
        period_of_report=period,
        options_scenario=options_scenario,
        lookthrough=lookthrough,
    )
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no holdings for CIK {cik} at {period.isoformat()}",
        )
    notes = [*_STANDARD_NOTES, NOTE_SECTOR_PENDING]
    if options_scenario is None:
        notes.insert(2, NOTE_OPTIONS_EXCLUDED)
    return ConcentrationResponse(
        as_of=snap.as_of,
        data_notes=notes,
        fund_cik=normalize_cik(cik),
        quarter=snap.quarter,
        hhi=snap.hhi,
        effective_n=snap.effective_n,
        top5=snap.top5,
        top10=snap.top10,
        largest_issuer=IssuerWeight(
            issuer_key=snap.largest_issuer[0], weight=snap.largest_issuer[1]
        ),
        sector_weights=snap.sector_weights,
        options_scenario=snap.options_scenario,
        combined_issuers=[
            CombinedIssuerWeight(
                issuer_key=c.issuer_key,
                equity_weight=c.equity_weight,
                option_delta_weight=c.option_delta_weight,
                combined_weight=c.combined_weight,
            )
            for c in snap.combined_issuers
        ],
        lookthrough=snap.lookthrough,
        lookthrough_coverage=snap.lookthrough_coverage,
        lookthrough_weights=snap.lookthrough_weights,
    )


@router.get(
    "/funds/{cik}/concentration/history",
    response_model=ConcentrationHistoryResponse,
)
def get_concentration_history_endpoint(
    cik: str,
    session: Annotated[Session, Depends(get_session)],
) -> ConcentrationHistoryResponse:
    _require_fund(session, cik)
    rows = get_concentration_history(session, cik=cik)
    return ConcentrationHistoryResponse(
        as_of=rows[-1]["as_of"] if rows else None,
        data_notes=_STANDARD_NOTES,
        fund_cik=normalize_cik(cik),
        history=[
            ConcentrationHistoryEntry(
                quarter=r["quarter"],
                as_of=r["as_of"],
                hhi=r["hhi"],
                top10=r["top10"],
            )
            for r in rows
        ],
    )


@router.get("/funds/{cik}/clusters", response_model=ClustersResponse)
def get_clusters_endpoint(
    cik: str,
    session: Annotated[Session, Depends(get_session)],
    quarter: Annotated[str | None, Query()] = None,
    rho: Annotated[float, Query(ge=0.0, le=1.0)] = 0.7,
    min_weight: Annotated[float, Query(ge=0.0, le=1.0)] = 0.005,
) -> ClustersResponse:
    _require_fund(session, cik)
    period = resolve_period(session, cik, quarter)
    result = get_clusters(
        session,
        cik=cik,
        period_of_report=period,
        rho_threshold=rho,
        min_weight=min_weight,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no holdings for CIK {cik} at {period.isoformat()}",
        )
    notes = [*_STANDARD_NOTES]
    if result.insufficient:
        notes.append(
            "insufficient price history for a reliable 252-day correlation — "
            "run `python -m concrisk.etl.prices` to backfill"
        )
    if result.missing_tickers:
        notes.append(
            f"no price data for {len(result.missing_tickers)} ticker(s); "
            "they were excluded from clustering"
        )
    return ClustersResponse(
        as_of=period,
        data_notes=notes,
        fund_cik=normalize_cik(cik),
        quarter=format_quarter(period),
        rho_threshold=result.rho_threshold,
        min_weight=result.min_weight,
        clusters=[
            ClusterEntry(
                cluster_id=c.cluster_id,
                tickers=list(c.tickers),
                weight=c.weight,
                avg_correlation=c.avg_correlation,
            )
            for c in result.clusters
        ],
        missing_tickers=result.missing_tickers,
        insufficient_price_data=result.insufficient,
    )
