# ConcRisk

Concentration risk analytics for institutional equity portfolios, built on public SEC 13F filings.

ConcRisk ingests quarterly holdings for a set of major funds and computes concentration metrics:
- Herfindahl-Hirschman Index (HHI), effective N, and top-N weights
- Sector exposure, ETF look-through, and options exposure under explicit delta scenarios
- Checks against a configurable limits framework

Results are served through a REST API, a monitoring dashboard, and a chatbot that answers risk questions by calling the API. The chatbot never generates numbers of its own.

> 🚧 In progress. See [Roadmap](#roadmap).

**Live:** _dashboard URL_ · _API docs URL_ · _demo video_

<!-- After `bash deploy/01-provision.sh` + `02-containerapps.sh`, replace the
     placeholders above with the Container Apps URLs printed by the scripts:
       dashboard: https://concrisk-dashboard.<envdomain>
       API docs:  https://concrisk-api.<envdomain>/docs
-->


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

50-question eval set covering numeric lookups, set questions, options scenarios, ETF look-through, correlation clusters, and 13F-limitation refusals. Current pass rate: **50/50 (100%)** against seeded Berkshire + Pershing Square data. Run yourself with:

```bash
uv run python evals/run_evals.py          # requires ANTHROPIC_API_KEY
```

See [`evals/`](evals/) for the question set and harness.

## Deployment

Full Azure deployment guide: [`deploy/README.md`](deploy/README.md). Three shell scripts (`01-provision.sh`, `02-containerapps.sh`, `03-deploy.sh`) take you from an empty subscription to live Container Apps in about 20 minutes.

Topology (SPEC §11):
- Postgres Flexible Server (Burstable Standard_B1ms)
- Azure Container Registry (Basic)
- Container Apps environment with two apps (API, dashboard) scaling to zero when idle
- Scheduled Container Apps Job for the daily ETL run

CI (`.github/workflows/ci.yml`) builds and pushes the Docker image to GHCR on every push to `main`. CD (`.github/workflows/deploy.yml`) is manual (`workflow_dispatch`) so there are no accidental prod pushes.

## Roadmap

- [x] Phase 0: Scaffold and CI
- [x] Phase 1: ETL
- [x] Phase 2: Risk engine and limits
- [x] Phase 3: API
- [x] Phase 4: Dashboard
- [x] Phase 5: Chatbot and evals
- [x] Phase 7: Look-through, options scenarios, correlation clusters
- [ ] Phase 6: Azure deployment (code complete; provisioning pending)
