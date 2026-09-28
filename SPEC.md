# ConcRisk — Specification

## 1. Goal

Measure and explain **concentration risk** in institutional equity portfolios using public SEC 13F-HR filings. Deliver it through a scheduled data pipeline, a tested risk engine, a REST API, a monitoring dashboard, and a chatbot that answers risk questions by calling the API. The chatbot never guesses numbers.

**Portfolio framing:** this mirrors an investment risk team's workflow: ingest holdings → compute exposures → check against a limits framework → report breaches → answer ad-hoc questions.

## 2. Scope

**In scope:** 10–20 named funds, last 8 quarters of 13F-HR filings, US equities + listed options reported on 13F, selected ETF look-through.

**Out of scope:** real-time data, short positions (not reported on 13F), fixed income, VaR/stress testing, user accounts/auth beyond a single API key.

### Known data limitations (state these in the README and in chatbot answers when relevant)

- 13F is quarterly and filed up to 45 days after quarter end, so holdings are stale by design.
- Long positions only. No shorts, so exposures are gross long, not net.
- Covers only "13(f) securities" (mostly US-listed equities, ETFs, listed options, some convertibles).
- Confidential treatment can omit positions.
- **Options: 13F reports the put/call flag, the underlying share count and the underlying's value, but not strike, expiry or premium.** True delta can't be computed. We report options exposure under explicit delta assumptions (§6.5), never as a precise number.

## 3. Repository layout

```
concrisk/
├── CLAUDE.md  SPEC.md  README.md  limits.yaml  .env.example
├── pyproject.toml  alembic.ini  Dockerfile
├── config/funds.yaml            # tracked funds: name + CIK
├── reference/                   # committed sample filings, ETF CSVs
├── data/                        # gitignored raw cache
├── src/concrisk/
│   ├── config.py                # pydantic-settings
│   ├── db/{models.py, session.py, migrations/}
│   ├── etl/{sec_client.py, parse_13f.py, openfigi.py, prices.py, etf.py, pipeline.py}
│   ├── risk/{weights.py, concentration.py, lookthrough.py, options.py, correlation.py, limits.py}
│   ├── services/                # DB + risk glue; used by API and chatbot
│   ├── api/{main.py, routers/, schemas.py}
│   └── chat/{tools.py, agent.py, prompts.py}
├── dashboard/app.py
├── evals/{questions.jsonl, run_evals.py}
├── tests/{unit/, integration/, fixtures/}
└── .github/workflows/ci.yml
```

**Layering rule:** `risk/` is pure. `services/` loads from DB and calls `risk/`. `api/` and `chat/` call only `services/`.

## 4. Data sources

| Source | Use | Access |
|---|---|---|
| SEC submissions API `data.sec.gov/submissions/CIK##########.json` | List a fund's filings | User-Agent header, ≤ 8 req/s |
| EDGAR archives `sec.gov/Archives/edgar/data/{cik}/{accession}/` (`index.json`) | Locate and fetch the information table XML | Same |
| OpenFIGI `POST /v3/mapping` (`ID_CUSIP`) | CUSIP → ticker, name, security type, exchange | `X-OPENFIGI-APIKEY` header |
| yfinance | Daily prices, sector/industry | Unofficial, cached |
| ETF issuer holdings CSVs (SPDR / iShares) | Look-through constituents | Manual download to `reference/` for MVP |

Note: OpenFIGI does not provide GICS-style sector. Sector comes from yfinance and is stored with `sector_source`.

### 13F parsing notes

- Filing types: `13F-HR` and `13F-HR/A`. Amendments are either `RESTATEMENT` (replaces the original, so use it) or `NEW HOLDINGS` (append to the original). Track this in `filings.amendment_type`.
- Information table fields used: `nameOfIssuer`, `titleOfClass`, `cusip`, `figi` (optional), `value`, `sshPrnamt`, `sshPrnamtType` (`SH`/`PRN`), `putCall` (absent / `Put` / `Call`), `investmentDiscretion`.
- `value` units: thousands before 2023-01-03, dollars on or after (see CLAUDE.md).
- The same CUSIP can appear on multiple rows (different managers/discretion). Aggregate per (filing, cusip, put_call).
- XML namespaces vary between filings. Parse namespace-agnostically.

## 5. Database schema

```
funds(id PK, cik UNIQUE, name, created_at)
filings(id PK, fund_id FK, accession_no UNIQUE, form_type, period_of_report DATE,
        filed_at DATE, amendment_type NULL, is_superseded BOOL, raw_path, loaded_at)
securities(id PK, cusip UNIQUE, figi, ticker, name, security_type, exch_code,
           sector, industry, sector_source, is_etf BOOL, mapped_at)
positions(id PK, filing_id FK, security_id FK, put_call NULL CHECK IN ('PUT','CALL'),
          shares NUMERIC, share_type, value_usd NUMERIC(20,2))
          UNIQUE(filing_id, security_id, put_call)
prices(security_id FK, date, close NUMERIC, PRIMARY KEY(security_id, date))
etf_constituents(etf_security_id FK, as_of DATE, constituent_security_id FK NULL,
                 constituent_ticker, weight NUMERIC)   -- weight as fraction
etl_runs(id PK, started_at, finished_at, status, stats JSONB)
etl_rejects(id PK, run_id FK, source, record JSONB, reason, created_at)
```

**"Current holdings" for a fund-quarter** = positions from the latest non-superseded filing for that `period_of_report`, with `NEW HOLDINGS` amendments merged in.

## 6. Risk metrics

Notation: fund *f*, quarter *q*, equity (non-option) positions *i* with market value *MVᵢ*. Unless stated otherwise, weights use **equity positions only** (options excluded), and **MV is the 13F reported value** (quarter-end).

### 6.1 Weights
wᵢ = MVᵢ / Σⱼ MVⱼ. Weights sum to 1 (test this).

### 6.2 Single-name and top-N
- Largest issuer weight: max wᵢ, aggregated by issuer (share classes of the same company, e.g. GOOG/GOOGL, roll up via a shared issuer key; start with ticker-root mapping in config).
- Top-N weight: sum of the N largest wᵢ (N = 5, 10).

### 6.3 Herfindahl-Hirschman Index
- HHI = Σ wᵢ². Range (1/n, 1].
- Effective number of positions: N_eff = 1 / HHI.
- Example for the test: w = (0.5, 0.3, 0.2) → HHI = 0.25 + 0.09 + 0.04 = 0.38; N_eff ≈ 2.63.

### 6.4 Sector concentration
w_s = Σ_{i∈s} wᵢ. Unknown sector goes in an `Unclassified` bucket and is reported, never dropped.

### 6.5 Options exposure (assumption-based)
For each option position with underlying value U (as reported):
- Gross notional: U (a CALL adds, a PUT subtracts in net terms).
- Delta-adjusted exposure = δ × U, with δ from a **named scenario**:
  - `notional`: CALL +1.0, PUT −1.0 (upper bound)
  - `atm`: CALL +0.5, PUT −0.5 (default approximation)
  - `ignore`: 0
- **Combined issuer exposure** = equity MV + Σ δ × U_option, divided by equity-only NAV, and reported alongside the scenario name.
- Every API response and chatbot answer involving options states the scenario. A Black-Scholes delta is possible only with assumed strike/expiry; don't pretend otherwise.

### 6.6 ETF look-through
For ETF position e with weight w_e and constituent weights c_{e,j}:
look-through weight of j = w_j(direct) + Σ_e w_e · c_{e,j}.
- Only ETFs with constituent data are expanded. The rest stay as a single line, and the response reports the unexpanded weight as `lookthrough_coverage`.
- Use the constituent file closest to (not after) the filing's `period_of_report`, and record `as_of`.
- Test case: fund holds 90% AAPL direct + 10% SPY, SPY holds 7% AAPL → look-through AAPL = 0.90 + 0.10 × 0.07 = 0.907.

### 6.7 Correlation clusters (Phase 7)
- Daily log returns over 252 trading days ending at `period_of_report`, for holdings above 0.5% weight.
- Distance d = √(0.5 × (1 − ρ)). Average-linkage hierarchical clustering, cut at ρ ≥ 0.7 (configurable).
- Cluster weight = Σ wᵢ in the cluster. Flags "hidden concentration" across different issuers.

## 7. Limits framework

Defined in `limits.yaml`. The engine evaluates every rule for every fund-quarter and returns:

```
Breach(fund, quarter, rule_id, metric, observed, threshold, severity, scope_key)
```

- `severity` ∈ {`warning`, `breach`}: a rule may define both thresholds.
- `scope_key` is the issuer / sector / cluster that triggered it.
- Rules can be overridden per fund (by CIK).

## 8. API (FastAPI)

All responses are JSON with `as_of` (period_of_report) and `data_notes` (limitations that apply). Auth: `X-API-Key` header in prod.

```
GET /health
GET /funds                                    list tracked funds + latest quarter
GET /funds/{cik}/quarters                     available quarters
GET /funds/{cik}/holdings?quarter=&top=       holdings with weights
GET /funds/{cik}/concentration?quarter=&lookthrough=false&options_scenario=atm
      → HHI, N_eff, top5, top10, largest issuer, sector weights
GET /funds/{cik}/concentration/history        HHI + top10 per quarter
GET /exposure/{ticker}?quarter=&lookthrough=  every fund's exposure to one issuer
GET /breaches?quarter=&severity=              limit breaches across funds
GET /compare?ciks=a,b&quarter=                side-by-side metrics
```

`quarter` format: `2026Q2`. Default = latest available.

## 9. Dashboard (Streamlit)

Calls the API (not the DB directly). Pages:
1. **Overview:** breach table across all funds, filterable by severity.
2. **Fund detail:** KPI cards (HHI, N_eff, top10, largest issuer), holdings treemap, sector bar chart, HHI history line, toggles for look-through and options scenario.
3. **Issuer exposure:** pick a ticker, see which funds hold it and at what weight.
4. **Compare:** two funds side by side.
5. **Ask:** chatbot UI.

## 10. Chatbot

- Anthropic Messages API with **tool use**. Tools map 1:1 to `services/` functions (same signatures as the API endpoints): `list_funds`, `get_concentration`, `get_holdings`, `get_exposure`, `get_breaches`, `compare_funds`, `get_concentration_history`.
- Tools accept fund names or CIKs. Resolve names server-side with fuzzy matching and return candidates on ambiguity.
- System prompt rules:
  - Answer only from tool results.
  - Cite quarter and figures.
  - State the options scenario and look-through setting when used.
  - Mention 13F limitations when the question implies current or short positions.
  - Say "I don't have that data" rather than estimate.
- Max 6 tool-call rounds per question. Log every tool call and result for debugging.
- No SQL generation, no code execution.

### Evals
- `evals/questions.jsonl` rows: `{"id", "question", "expected": {...}, "check": "numeric|set|contains|refusal", "tolerance"}`.
- Expected values computed by hand or via `services/` directly, never by the chatbot.
- `run_evals.py` reports accuracy by check type. Target ≥ 90% before calling Phase 5 done. Include refusal cases (e.g. "What is Citadel's short position in TSLA?").

## 11. Deployment (Azure)

- Resource group `rg-concrisk`.
- Azure Database for PostgreSQL Flexible Server, smallest burstable tier.
- Azure Container Registry. One image, three entrypoints: `api`, `dashboard`, `etl`.
- Container Apps: `concrisk-api`, `concrisk-dashboard`.
- Container Apps **Job** `concrisk-etl` on cron (daily; the pipeline no-ops if there are no new filings).
- Secrets in Container Apps secrets (or Key Vault), never in the image.
- Budget alert on the subscription.

## 12. CI (GitHub Actions)

On PR and push to main: `uv sync` → ruff → pyright → pytest (unit + integration against a Postgres service container). Build the Docker image on main.

## 13. Phases

| # | Phase | Done when |
|---|---|---|
| 0 | Scaffold | Layout, pyproject, config, ruff/pytest/pyright pass, CI green, Alembic initialized |
| 1 | ETL | Pipeline loads 8 quarters for all funds in `config/funds.yaml`. Parser tested on `reference/` filings (both value-unit regimes). OpenFIGI mapping cached. Rejects logged. Row counts manually spot-checked against EDGAR for 2 funds. |
| 2 | Risk engine | §6.1–6.4 + limits (§7) implemented, each with hand-computed tests |
| 3 | API | Endpoints in §8 (except look-through/options params). Integration tests. |
| 4 | Dashboard | Pages 1–4 working against local API |
| 5 | Chatbot | Tools + agent + Ask page. Eval set ≥ 20 questions at ≥ 90%. |
| 6 | Deploy | Running on Azure, ETL job scheduled, README live URLs |
| 7 | Extensions | Look-through (§6.6), options scenarios (§6.5), correlation clusters (§6.7), eval set to 50, optional Power BI report |

## 14. Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-09-28 | Azure over AWS | Student credits, no card; posting lists Azure; pairs with Power BI |
| 2026-09-28 | Streamlit for primary dashboard | Deployable from Mac, same Python stack. Power BI optional in Phase 7 on Windows. |
| 2026-09-28 | Options via delta scenarios, not Black-Scholes | 13F omits strike/expiry |
| 2026-09-28 | Chatbot uses tool calling, no text-to-SQL | Grounded, auditable, testable |
