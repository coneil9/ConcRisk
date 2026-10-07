"""Daily close prices from yfinance → Postgres cache.

yfinance is unofficial and flaky (per CLAUDE.md). This module wraps
it with:
- Retry + exponential backoff on failure
- Small sleep between calls (yfinance has silent rate limits)
- Postgres cache keyed on (security_id, date); only missing dates
  are refetched

CLI:
    uv run python -m concrisk.etl.prices [--fund CIK] [--days 252]

With no --fund, backfills every ticker in `securities` that has a
mapped ticker. --days N backfills the last N trading days per ticker
ending today (default 252 — SPEC §6.7's requirement for correlation
clusters).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import Filing, Fund, Position, Price, Security
from concrisk.db.session import SessionLocal

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 252  # SPEC §6.7 — one trading year
RETRY_ATTEMPTS = 3
INTER_CALL_SLEEP = 0.5


def _fetch_one(ticker: str, start: date, end: date) -> list[tuple[date, Decimal]]:
    """One ticker, one date range. Returns [(date, close), ...].
    Retries 3× with exponential backoff on any yfinance error.
    """
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            data = cast(
                Any,
                yf.download(
                    ticker,
                    start=start.isoformat(),
                    end=(end + timedelta(days=1)).isoformat(),
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                ),
            )
            if data is None or data.empty:
                return []
            # yfinance returns a MultiIndex (field, ticker) when threads=False
            # for a single ticker — flatten it.
            close_series = data["Close"]
            if hasattr(close_series, "columns") and ticker in close_series.columns:
                close_series = close_series[ticker]
            rows: list[tuple[date, Decimal]] = []
            for ts, close in cast(Any, close_series).items():
                if close is None:
                    continue
                try:
                    rows.append((ts.date(), Decimal(str(round(float(close), 4)))))
                except (ValueError, TypeError):
                    continue
            return rows
        except Exception as e:  # yfinance throws a mix of types
            last_error = e
            sleep_for = 2**attempt
            logger.warning("yfinance %s attempt %d failed: %s", ticker, attempt + 1, e)
            time.sleep(sleep_for)
    assert last_error is not None
    raise last_error


def _target_tickers(session: Session, cik: str | None) -> list[tuple[int, str]]:
    """Pick (security_id, ticker) rows to fetch prices for.

    Without --fund: every security with a mapped ticker that isn't an ETF.
    With --fund: only securities held by that fund in a non-superseded
    filing (keeps prices scoped to what we actually need for clustering).
    """
    stmt = select(Security.id, Security.ticker).where(
        Security.ticker.is_not(None),
        Security.ticker != "",
        Security.is_etf.is_(False),
    )
    if cik is not None:
        fund = session.execute(select(Fund).where(Fund.cik == cik.zfill(10))).scalar_one_or_none()
        if fund is None:
            return []
        stmt = stmt.where(
            Security.id.in_(
                select(Position.security_id)
                .join(Filing, Filing.id == Position.filing_id)
                .where(Filing.fund_id == fund.id, Filing.is_superseded.is_(False))
            )
        )
    return [(int(sid), str(t)) for sid, t in session.execute(stmt).all()]


def _existing_dates(session: Session, security_id: int, start: date, end: date) -> set[date]:
    rows = (
        session.execute(
            select(Price.date).where(
                Price.security_id == security_id,
                Price.date >= start,
                Price.date <= end,
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def backfill_prices(
    session: Session, cik: str | None = None, days: int = DEFAULT_DAYS
) -> dict[str, int]:
    """Fetch missing daily closes for every target ticker. Returns
    {"tickers": N, "fetched": N, "rows": N, "errors": N}."""
    end = date.today()
    start = end - timedelta(days=int(days * 1.5))  # calendar-day cushion for weekends
    targets = _target_tickers(session, cik)

    stats = {"tickers": len(targets), "fetched": 0, "rows": 0, "errors": 0}
    for i, (security_id, ticker) in enumerate(targets):
        existing = _existing_dates(session, security_id, start, end)
        # Only fetch if we have fewer than `days` cached closes.
        if len(existing) >= days:
            continue
        logger.info("yfinance %s (%d/%d)", ticker, i + 1, len(targets))
        try:
            rows = _fetch_one(ticker, start, end)
        except Exception as e:
            stats["errors"] += 1
            logger.warning("yfinance %s failed after retries: %s", ticker, e)
            continue
        stats["fetched"] += 1
        new_rows = 0
        for d, close in rows:
            if d in existing:
                continue
            session.add(Price(security_id=security_id, date=d, close=close))
            new_rows += 1
        if new_rows:
            session.commit()
            stats["rows"] += new_rows
        time.sleep(INTER_CALL_SLEEP)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concrisk.etl.prices")
    parser.add_argument("--fund", type=str, default=None, help="CIK filter")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Trading-day history")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with SessionLocal() as session:
        stats = backfill_prices(session, cik=args.fund, days=args.days)
        print(f"prices done: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
