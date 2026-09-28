# CLAUDE.md — ConcRisk

Concentration risk analytics on SEC 13F institutional holdings: ETL → risk engine → API → dashboard → LLM chatbot. Full design lives in `SPEC.md`. Read it before starting any task, and check which phase we're in.

## How to work in this repo

- **Plan before code.** For any task touching more than one module, propose a plan and wait for approval.
- **One phase at a time.** Only build what the current phase in `SPEC.md` calls for. Don't scaffold future phases.
- **Small commits** with conventional messages (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`). One logical change per commit.
- **Ask, don't guess**, on anything touching financial logic (weights, exposure, limits). A wrong number that looks right is the worst failure mode in this project.
- Update `SPEC.md` when a design decision changes, and add a line to its Decision Log.

## Stack

- Python 3.12, managed with **uv**. Add deps with `uv add <pkg>` (dev: `uv add --dev <pkg>`). Run everything with `uv run ...`. Never use pip directly or create venvs manually.
- Postgres 16. Local dev runs in Docker (`concrisk-db` container, `DATABASE_URL` in `.env`). Prod is Azure Database for PostgreSQL.
- SQLAlchemy 2.x (typed ORM, `Mapped[]`) + Alembic for migrations. psycopg 3 driver.
- pandas / NumPy for analytics; SciPy for clustering.
- FastAPI + Pydantic v2 for the API.
- Streamlit for the dashboard.
- Anthropic Python SDK for the chatbot (tool calling). Model name comes from `ANTHROPIC_MODEL` in `.env`.
- Deploy: Docker images on Azure Container Apps; ETL as a scheduled Container Apps Job.
- Tooling: ruff (lint + format), pytest, pyright (basic mode).

## Commands

```bash
uv run pytest                     # tests
uv run ruff check . && uv run ruff format .
uv run pyright
uv run alembic upgrade head       # apply migrations
uv run python -m concrisk.etl.pipeline --help
uv run uvicorn concrisk.api.main:app --reload
uv run streamlit run dashboard/app.py
```

Run tests, ruff and pyright before declaring any task done.

## Code conventions

- Package lives in `src/concrisk/` (layout in `SPEC.md`). Absolute imports only.
- Type hints on every function signature. No `Any` unless unavoidable.
- Config and secrets only through `concrisk.config` (pydantic-settings reading `.env`). Never read `os.environ` elsewhere.
- **Money:** store as `NUMERIC(20,2)` in Postgres and `Decimal` at the DB boundary. Convert to float only inside the risk engine.
- **Weights** are fractions (0.12), never percentages (12). Format as % only in the UI and chatbot output.
- Pure functions in `risk/`: DataFrames in, DataFrames or dataclasses out, no DB or network calls. This makes them trivially testable.
- Logging via `logging` (module-level `logger`), never `print` outside CLIs.

## Testing rules

- Every risk metric function gets a unit test with a **hand-computed expected value** in a comment (e.g. 3 positions, show the HHI arithmetic).
- Parser tests run against the real filings in `reference/`, not invented XML.
- Network calls are mocked in tests. No test hits SEC, OpenFIGI, Yahoo or Anthropic.
- Chatbot correctness is measured by `evals/`, not unit tests.

## External data rules (non-negotiable)

- **SEC EDGAR:** every request sends `User-Agent: $SEC_USER_AGENT`. Throttle to ≤ 8 req/s across the process. Cache raw filings under `data/raw/sec/` and never re-download a filing already on disk.
- **13F value units:** filings dated before 2023-01-03 report `value` in **thousands** of USD; on or after, in **whole dollars**. Normalize to dollars at parse time based on the filing date. Test both cases.
- **OpenFIGI:** batch CUSIPs (max jobs per request per current API docs), respect the keyed rate limit, and cache every mapping in the `securities` table so a CUSIP is resolved once.
- **yfinance** is unofficial and flaky. Wrap it, retry with backoff, cache prices in Postgres, and never call it from the API request path.
- **Anthropic:** called only from `concrisk.chat`. Never send raw DB dumps to the model. Only tool results.

## Security

- Never hardcode keys. Never print or log key values. Never put them in prompts, tests or fixtures.
- `.env` is gitignored. When adding a new setting, add its name to `.env.example` with a placeholder.
- `data/` is gitignored (raw filings, caches). `reference/` is committed.

## Don't

- Don't add dependencies without saying why.
- Don't let the chatbot write or execute SQL. It only calls typed tools.
- Don't silently drop rows during ETL. Log counts and write rejects to `etl_rejects`.
- Don't "fix" a failing test by changing its expected value unless the hand calculation was wrong, and say so explicitly.
