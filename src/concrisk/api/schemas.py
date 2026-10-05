from datetime import date

from pydantic import BaseModel, Field

# Fixed vocabulary for `data_notes`. Endpoints attach a subset relevant
# to what they returned; SPEC §8 says every response carries this.
NOTE_QUARTERLY_STALE = (
    "13F is quarterly and filed up to 45 days after quarter end — "
    "holdings may be up to ~135 days stale"
)
NOTE_LONG_ONLY = "long positions only; no shorts (13F does not report them)"
NOTE_SECTOR_PENDING = "sector data is populated in Phase 7; positions may show 'Unclassified'"
NOTE_OPTIONS_EXCLUDED = "options positions excluded from weights (SPEC §6)"


class ResponseBase(BaseModel):
    as_of: date | None = None
    data_notes: list[str] = Field(default_factory=list)


class FundSummary(BaseModel):
    cik: str
    name: str
    latest_quarter: str | None = None


class FundsResponse(ResponseBase):
    funds: list[FundSummary]


class QuartersResponse(ResponseBase):
    fund_cik: str
    quarters: list[str]


class HoldingRow(BaseModel):
    cusip: str
    ticker: str | None
    name: str | None
    sector: str | None
    shares: float
    value_usd: float
    weight: float
    put_call: str | None


class HoldingsResponse(ResponseBase):
    fund_cik: str
    quarter: str
    total_value_usd: float
    holdings: list[HoldingRow]


class IssuerWeight(BaseModel):
    issuer_key: str
    weight: float


class CombinedIssuerWeight(BaseModel):
    issuer_key: str
    equity_weight: float
    option_delta_weight: float
    combined_weight: float


class ConcentrationResponse(ResponseBase):
    fund_cik: str
    quarter: str
    hhi: float
    effective_n: float
    top5: float
    top10: float
    largest_issuer: IssuerWeight
    sector_weights: dict[str, float]
    # Phase 7 — populated only when the corresponding query param is set.
    options_scenario: str | None = None
    combined_issuers: list[CombinedIssuerWeight] = Field(default_factory=list)
    lookthrough: bool = False
    lookthrough_coverage: float | None = None
    lookthrough_weights: dict[str, float] = Field(default_factory=dict)


class ConcentrationHistoryEntry(BaseModel):
    quarter: str
    as_of: date
    hhi: float
    top10: float


class ConcentrationHistoryResponse(ResponseBase):
    fund_cik: str
    history: list[ConcentrationHistoryEntry]


class ClusterEntry(BaseModel):
    cluster_id: int
    tickers: list[str]
    weight: float
    avg_correlation: float


class ClustersResponse(ResponseBase):
    fund_cik: str
    quarter: str
    rho_threshold: float
    min_weight: float
    clusters: list[ClusterEntry]
    missing_tickers: list[str]
    insufficient_price_data: bool


class ExposureRow(BaseModel):
    fund_cik: str
    fund_name: str
    quarter: str
    as_of: date
    weight: float
    value_usd: float
    ticker: str
    issuer_key: str
    # Phase 7 — only when lookthrough=true.
    lookthrough_weight: float | None = None
    lookthrough_coverage: float | None = None


class ExposureResponse(ResponseBase):
    ticker: str
    lookthrough: bool = False
    exposures: list[ExposureRow]


class BreachRow(BaseModel):
    fund_cik: str
    quarter: str
    rule_id: str
    metric: str
    observed: float
    threshold: float
    severity: str
    scope_key: str | None


class BreachesResponse(ResponseBase):
    breaches: list[BreachRow]


class CompareResponse(ResponseBase):
    quarter: str | None
    funds: list[ConcentrationResponse]
