from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from concrisk.api.schemas import (
    NOTE_LONG_ONLY,
    NOTE_OPTIONS_EXCLUDED,
    NOTE_QUARTERLY_STALE,
    NOTE_SECTOR_PENDING,
    BreachesResponse,
    BreachRow,
)
from concrisk.db.session import get_session
from concrisk.services import breaches_for_quarter, parse_quarter

router = APIRouter()


@router.get("/breaches", response_model=BreachesResponse)
def get_breaches(
    session: Annotated[Session, Depends(get_session)],
    quarter: Annotated[str | None, Query()] = None,
    severity: Annotated[Literal["warning", "breach"] | None, Query()] = None,
) -> BreachesResponse:
    period = None
    if quarter:
        try:
            period = parse_quarter(quarter)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    breaches = breaches_for_quarter(session, period_of_report=period, severity=severity)
    return BreachesResponse(
        as_of=period,
        data_notes=[
            NOTE_QUARTERLY_STALE,
            NOTE_LONG_ONLY,
            NOTE_OPTIONS_EXCLUDED,
            NOTE_SECTOR_PENDING,
        ],
        breaches=[
            BreachRow(
                fund_cik=b.fund_cik,
                quarter=b.quarter,
                rule_id=b.rule_id,
                metric=b.metric,
                observed=b.observed,
                threshold=b.threshold,
                severity=b.severity,
                scope_key=b.scope_key,
            )
            for b in breaches
        ],
    )
