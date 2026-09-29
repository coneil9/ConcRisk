from datetime import date
from typing import Any

import pandas as pd
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from concrisk.services import latest_period_for_fund, parse_quarter


def resolve_period(session: Session, cik: str, quarter: str | None) -> date:
    """Resolve the ?quarter=YYYYQn param, defaulting to the fund's latest
    non-superseded period. 404 if the fund has no filings."""
    if quarter:
        try:
            return parse_quarter(quarter)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    period = latest_period_for_fund(session, cik)
    if period is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no filings loaded for CIK {cik}",
        )
    return period


def none_if_na(value: Any) -> Any:
    """Convert pandas NaN/NA to Python None so Pydantic accepts it."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value
