from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from concrisk.api.schemas import (
    NOTE_LONG_ONLY,
    NOTE_OPTIONS_EXCLUDED,
    NOTE_QUARTERLY_STALE,
    ExposureResponse,
)
from concrisk.api.schemas import ExposureRow as ExposureRowSchema
from concrisk.db.session import get_session
from concrisk.services import issuer_exposure_across_funds, parse_quarter

router = APIRouter()


@router.get("/exposure/{ticker}", response_model=ExposureResponse)
def get_exposure(
    ticker: str,
    session: Annotated[Session, Depends(get_session)],
    quarter: Annotated[str | None, Query()] = None,
) -> ExposureResponse:
    period = None
    if quarter:
        try:
            period = parse_quarter(quarter)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    exposures = issuer_exposure_across_funds(session, ticker=ticker, period_of_report=period)
    if not exposures:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no tracked fund holds {ticker.upper()}",
        )
    latest = max((e.as_of for e in exposures), default=None)
    return ExposureResponse(
        as_of=latest,
        data_notes=[NOTE_QUARTERLY_STALE, NOTE_LONG_ONLY, NOTE_OPTIONS_EXCLUDED],
        ticker=ticker.upper(),
        exposures=[
            ExposureRowSchema(
                fund_cik=e.fund_cik,
                fund_name=e.fund_name,
                quarter=e.quarter,
                as_of=e.as_of,
                weight=e.weight,
                value_usd=e.value_usd,
                ticker=e.ticker,
                issuer_key=e.issuer_key,
            )
            for e in exposures
        ],
    )
