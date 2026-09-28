# ConcRisk

Concentration risk analytics for institutional equity portfolios, built on public SEC 13F filings.

ConcRisk ingests quarterly holdings for a set of major funds and computes concentration metrics:
- Herfindahl-Hirschman Index (HHI), effective N, and top-N weights
- Sector exposure, ETF look-through, and options exposure under explicit delta scenarios
- Checks against a configurable limits framework

Results are served through a REST API, a monitoring dashboard, and a chatbot that answers risk questions by calling the API. The chatbot never generates numbers of its own.

> 🚧 In progress. See [Roadmap](#roadmap).

**Live:** _dashboard URL_ · _API docs URL_ · _demo video_

## Architecture

_(diagram: SEC EDGAR / OpenFIGI / prices → ETL job → Postgres → risk engine → FastAPI → Streamlit dashboard + LLM chatbot)_

| Layer | Tech |
|---|---|
| ETL | Python, pandas, SQLAlchemy, Alembic; scheduled Azure Container Apps Job |
| Storage | PostgreSQL (Azure Database for PostgreSQL) |
| Risk engine | pandas, NumPy, SciPy (pure, unit-tested functions) |
| API | FastAPI, Pydantic |
| Dashboard | Streamlit |
| Chatbot | Anthropic Claude with tool calling, plus an eval harness |
| Infra / CI | Docker, Azure Container Apps, GitHub Actions |

## Metrics

| Metric | Definition |
|---|---|
| Weight | wᵢ = MVᵢ / Σ MV (equity positions) |
| HHI | Σ wᵢ² |
| Effective N | 1 / HHI |
| Top-N | Sum of N largest weights |
| Look-through | Direct weight + Σ ETF weight × constituent weight |
| Options exposure | δ × underlying value, with δ from a named scenario (`notional`, `atm`, `ignore`) |

Full definitions are in [SPEC.md](SPEC.md#6-risk-metrics).

## Data limitations

- 13F is quarterly, filed up to 45 days after quarter end.
- Long positions only, with no shorts, so all exposures are gross long.
- Options are reported without strike or expiry, so options exposure is scenario-based.
- Confidential treatment can omit positions.

## Quickstart

```bash
cp .env.example .env                # fill in keys
docker run -d --name concrisk-db -e POSTGRES_USER=concrisk -e POSTGRES_PASSWORD=localdev \
  -e POSTGRES_DB=concrisk -p 5432:5432 postgres:16
uv sync
uv run alembic upgrade head
uv run python -m concrisk.etl.pipeline --quarters 8
uv run uvicorn concrisk.api.main:app --reload
uv run streamlit run dashboard/app.py
```

## Example chatbot questions

- "Which funds breach the 10% single-issuer limit this quarter?"
- "How has Berkshire's HHI changed over the last 8 quarters?"
- "Which funds have the most exposure to NVDA, including through ETFs?"

## Chatbot evaluation

_Accuracy on N eval questions: X% (numeric), Y% (refusals). See `evals/`._

## Roadmap

- [ ] Phase 0: Scaffold and CI
- [ ] Phase 1: ETL
- [ ] Phase 2: Risk engine and limits
- [ ] Phase 3: API
- [ ] Phase 4: Dashboard
- [ ] Phase 5: Chatbot and evals
- [ ] Phase 6: Azure deployment
- [ ] Phase 7: Look-through, options scenarios, correlation clusters
