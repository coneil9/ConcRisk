"""Backfill securities.sector / .industry from yfinance.

SPEC §4: "Sector comes from yfinance and is stored with `sector_source`."
Deferred in Phase 1 (yfinance wasn't a dep yet). Lands here now that
Phase 7 ships yfinance.

CLI:
    uv run python -m concrisk.etl.sectors [--fund CIK] [--force]

Without --fund, backfills every security that has a ticker and no
sector yet. --force re-fetches even if sector is already populated.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any, cast

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import Filing, Fund, Position, Security
from concrisk.db.session import SessionLocal

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
INTER_CALL_SLEEP = 0.5


def _fetch_sector(ticker: str) -> tuple[str | None, str | None]:
    """Returns (sector, industry) for one ticker; None/None on failure."""
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            info = cast(Any, yf.Ticker(ticker).info)
            if not isinstance(info, dict):
                return None, None
            return info.get("sector") or None, info.get("industry") or None
        except Exception as e:
            last_error = e
            time.sleep(2**attempt)
    logger.warning("yfinance sector %s failed: %s", ticker, last_error)
    return None, None


def _target_securities(session: Session, cik: str | None, force: bool) -> list[Security]:
    stmt = select(Security).where(
        Security.ticker.is_not(None),
        Security.ticker != "",
        Security.is_etf.is_(False),
    )
    if not force:
        stmt = stmt.where(Security.sector.is_(None))
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
    return list(session.execute(stmt).scalars().all())


def backfill_sectors(
    session: Session, cik: str | None = None, force: bool = False
) -> dict[str, int]:
    targets = _target_securities(session, cik, force)
    stats = {"tickers": len(targets), "updated": 0, "no_data": 0}
    for i, sec in enumerate(targets):
        logger.info("yfinance %s (%d/%d)", sec.ticker, i + 1, len(targets))
        sector, industry = _fetch_sector(sec.ticker or "")
        if sector is None and industry is None:
            stats["no_data"] += 1
        else:
            sec.sector = sector
            sec.industry = industry
            sec.sector_source = "yfinance"
            stats["updated"] += 1
        session.commit()
        time.sleep(INTER_CALL_SLEEP)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concrisk.etl.sectors")
    parser.add_argument("--fund", type=str, default=None, help="CIK filter")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if sector is set")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    with SessionLocal() as session:
        stats = backfill_sectors(session, cik=args.fund, force=args.force)
        print(f"sectors done: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
