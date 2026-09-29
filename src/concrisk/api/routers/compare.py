from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from concrisk.api.deps import resolve_period
from concrisk.api.schemas import (
    NOTE_LONG_ONLY,
    NOTE_OPTIONS_EXCLUDED,
    NOTE_QUARTERLY_STALE,
    NOTE_SECTOR_PENDING,
    CompareResponse,
    ConcentrationResponse,
    IssuerWeight,
)
from concrisk.db.session import get_session
from concrisk.services import get_concentration, get_fund, normalize_cik

router = APIRouter()

_NOTES = [
    NOTE_QUARTERLY_STALE,
    NOTE_LONG_ONLY,
    NOTE_OPTIONS_EXCLUDED,
    NOTE_SECTOR_PENDING,
]


@router.get("/compare", response_model=CompareResponse)
def compare_funds(
    session: Annotated[Session, Depends(get_session)],
    ciks: Annotated[str, Query(description="comma-separated CIKs, 2+")],
    quarter: Annotated[str | None, Query()] = None,
) -> CompareResponse:
    cik_list = [c.strip() for c in ciks.split(",") if c.strip()]
    if len(cik_list) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pass at least 2 comma-separated CIKs to /compare",
        )

    results: list[ConcentrationResponse] = []
    for cik in cik_list:
        if get_fund(session, cik) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown or unloaded CIK {cik}",
            )
        period = resolve_period(session, cik, quarter)
        snap = get_concentration(session, cik=cik, period_of_report=period)
        if snap is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no holdings for CIK {cik} at {period.isoformat()}",
            )
        results.append(
            ConcentrationResponse(
                as_of=snap.as_of,
                data_notes=_NOTES,
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
            )
        )
    return CompareResponse(
        as_of=max((r.as_of for r in results if r.as_of), default=None),
        data_notes=_NOTES,
        quarter=quarter,
        funds=results,
    )
