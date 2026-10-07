"""ETF constituents loader.

Reads a CSV in the format:
    ticker,weight
    AAPL,0.0712
    MSFT,0.0686
    ...

Filename convention: `{ETF_TICKER}-{YYYYMMDD}.csv`. The CLI parses
the ETF ticker and as_of date from the filename; override with
--etf-ticker and --as-of if needed. Weight is a fraction (0.0712
means 7.12%). Weights do NOT have to sum to 1 — many CSVs truncate
to the top-N holdings and the look-through engine reports the
unexpanded remainder as `lookthrough_coverage`.

CLI:
    uv run python -m concrisk.etl.etf reference/etf/SPY-20260930.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.db.models import EtfConstituent, Security
from concrisk.db.session import SessionLocal

logger = logging.getLogger(__name__)

# ETFs we ship real CUSIPs for — anything else gets a synthetic one.
KNOWN_ETF_CUSIPS = {
    "SPY": "78462F103",
    "QQQ": "46090E103",
    "IVV": "464287200",
    "VOO": "922908363",
    "VTI": "922908769",
    "DIA": "73935A104",
    "IWM": "464287655",
}

_FILENAME_RE = re.compile(r"^(?P<ticker>[A-Z]+)-(?P<ymd>\d{8})\.csv(?:\.gz)?$")


def _parse_filename(path: Path) -> tuple[str, date] | None:
    m = _FILENAME_RE.match(path.name)
    if not m:
        return None
    return m.group("ticker"), datetime.strptime(m.group("ymd"), "%Y%m%d").date()


def _ensure_etf_security(session: Session, ticker: str) -> Security:
    """Find or create the Security row for an ETF; flip is_etf=True."""
    sec = session.execute(
        select(Security).where(Security.ticker == ticker, Security.is_etf.is_(True))
    ).scalar_one_or_none()
    if sec is None:
        cusip = KNOWN_ETF_CUSIPS.get(ticker, f"ETF-{ticker}")
        sec = session.execute(select(Security).where(Security.cusip == cusip)).scalar_one_or_none()
        if sec is None:
            sec = Security(cusip=cusip, ticker=ticker, name=ticker, is_etf=True)
            session.add(sec)
            session.flush()
        else:
            sec.ticker = ticker
            sec.is_etf = True
    return sec


def _load_rows(path: Path) -> list[tuple[str, float]]:
    """Parse (ticker, weight) rows from a CSV; supports .gz transparently."""
    if path.suffix == ".gz":
        import gzip

        with gzip.open(path, "rt", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [(r["ticker"].strip().upper(), float(r["weight"])) for r in reader]
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [(r["ticker"].strip().upper(), float(r["weight"])) for r in reader]


def load_etf_csv(session: Session, csv_path: Path, etf_ticker: str, as_of: date) -> int:
    """Load one ETF constituents CSV into the database.

    Idempotent: existing (etf, as_of, ticker) rows are overwritten.
    Returns the number of constituent rows written.
    """
    etf = _ensure_etf_security(session, etf_ticker)
    rows = _load_rows(csv_path)
    if not rows:
        return 0

    # Clear existing snapshot for this (etf, as_of).
    existing = (
        session.execute(
            select(EtfConstituent).where(
                EtfConstituent.etf_security_id == etf.id,
                EtfConstituent.as_of == as_of,
            )
        )
        .scalars()
        .all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    # Resolve each constituent ticker to a security_id when possible.
    tickers = [t for t, _ in rows]
    sec_rows = session.execute(select(Security).where(Security.ticker.in_(tickers))).scalars().all()
    sec_by_ticker: dict[str, int] = {}
    for s in sec_rows:
        if s.ticker:
            sec_by_ticker[s.ticker] = s.id

    for ticker, weight in rows:
        session.add(
            EtfConstituent(
                etf_security_id=etf.id,
                as_of=as_of,
                constituent_security_id=sec_by_ticker.get(ticker),
                constituent_ticker=ticker,
                weight=weight,
            )
        )

    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concrisk.etl.etf")
    parser.add_argument("csv", type=Path, help="Path to ETF constituents CSV")
    parser.add_argument(
        "--etf-ticker",
        type=str,
        default=None,
        help="Override ETF ticker (default: parsed from filename)",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="Override as-of date YYYY-MM-DD (default: parsed from filename)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    etf_ticker = args.etf_ticker
    as_of_date = date.fromisoformat(args.as_of) if args.as_of else None
    if not etf_ticker or not as_of_date:
        parsed = _parse_filename(args.csv)
        if parsed is None:
            print(
                f"error: could not parse ETF ticker + date from {args.csv.name!r}; "
                "use --etf-ticker and --as-of",
                file=sys.stderr,
            )
            return 2
        etf_ticker = etf_ticker or parsed[0]
        as_of_date = as_of_date or parsed[1]

    with SessionLocal() as session:
        count = load_etf_csv(session, args.csv, etf_ticker, as_of_date)
        session.commit()
        print(f"loaded {count} constituents for {etf_ticker} as of {as_of_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
