"""Services: DB + risk-engine glue. Called by api/ and chat/, never
directly by risk/ or db/ code.
"""

from concrisk.services.breaches import breaches_for_quarter
from concrisk.services.concentration import (
    CombinedIssuer,
    ConcentrationSnapshot,
    get_concentration,
    get_concentration_history,
)
from concrisk.services.etf import load_latest_constituents
from concrisk.services.exposure import ExposureRow, issuer_exposure_across_funds
from concrisk.services.funds import (
    FundSummary,
    latest_period_for_fund,
    list_available_periods,
    list_funds_with_latest_quarter,
    list_tracked_funds,
)
from concrisk.services.holdings import build_holdings_df, get_fund, normalize_cik
from concrisk.services.quarters import format_quarter, parse_quarter

__all__ = [
    "CombinedIssuer",
    "ConcentrationSnapshot",
    "ExposureRow",
    "FundSummary",
    "breaches_for_quarter",
    "build_holdings_df",
    "format_quarter",
    "get_concentration",
    "get_concentration_history",
    "get_fund",
    "issuer_exposure_across_funds",
    "latest_period_for_fund",
    "list_available_periods",
    "list_funds_with_latest_quarter",
    "list_tracked_funds",
    "load_latest_constituents",
    "normalize_cik",
    "parse_quarter",
]
