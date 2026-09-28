from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from concrisk.db.models import EtlReject, EtlRun, Filing, Fund, Position, Security
from concrisk.db.session import SessionLocal
from concrisk.etl.openfigi import OpenFigiClient, map_cusips
from concrisk.etl.parse_13f import (
    ParseError,
    aggregate_positions,
    parse_cover,
    parse_information_table,
)
from concrisk.etl.sec_client import SecClient, SubmissionRow

logger = logging.getLogger(__name__)

FUNDS_YAML = Path("config/funds.yaml")


def _load_funds(path: Path, only: set[str] | None) -> list[tuple[str, str]]:
    data = yaml.safe_load(path.read_text())
    rows = [(str(f["cik"]).zfill(10), str(f["name"])) for f in data["funds"]]
    if only is not None:
        wanted = {c.zfill(10) for c in only}
        rows = [r for r in rows if r[0] in wanted]
    return rows


def _period_cutoff(quarters: int) -> date:
    # Rough: N quarters back plus 60-day filing lag margin.
    return date.today() - timedelta(days=quarters * 92 + 60)


def _upsert_fund(session: Session, cik: str, name: str) -> Fund:
    fund = session.execute(select(Fund).where(Fund.cik == cik)).scalar_one_or_none()
    if fund is None:
        fund = Fund(cik=cik, name=name)
        session.add(fund)
        session.flush()
    elif fund.name != name:
        fund.name = name
    return fund


def _existing_accessions(session: Session) -> set[str]:
    rows = session.execute(select(Filing.accession_no)).scalars().all()
    return set(rows)


def _get_or_create_security(session: Session, cusip: str) -> Security:
    sec = session.execute(select(Security).where(Security.cusip == cusip)).scalar_one_or_none()
    if sec is None:
        sec = Security(cusip=cusip)
        session.add(sec)
        session.flush()
    return sec


@contextmanager
def _managed_run(session: Session, dry_run: bool) -> Iterator[EtlRun | None]:
    if dry_run:
        yield None
        return
    run_row = EtlRun(started_at=datetime.now(UTC), status="running")
    session.add(run_row)
    session.commit()
    try:
        yield run_row
    except Exception:
        run_row.finished_at = datetime.now(UTC)
        run_row.status = "error"
        session.commit()
        raise


def _load_filing(
    session: Session,
    sec: SecClient,
    figi: OpenFigiClient,
    fund: Fund,
    row: SubmissionRow,
    run_id: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Load one filing. Returns (positions_written, rejects_written)."""
    artifacts = sec.fetch_filing(fund.cik, row.accession_no)
    cover = parse_cover(artifacts.cover_path)

    if cover.amendment_type == "RESTATEMENT" and not dry_run:
        session.execute(
            update(Filing)
            .where(
                Filing.fund_id == fund.id,
                Filing.period_of_report == cover.period_of_report,
                Filing.accession_no != row.accession_no,
            )
            .values(is_superseded=True)
        )

    rejects = 0

    def on_row_error(err: ParseError) -> None:
        nonlocal rejects
        rejects += 1
        if not dry_run:
            session.add(
                EtlReject(
                    run_id=run_id,
                    source="parser",
                    record={"accession_no": row.accession_no},
                    reason=str(err),
                )
            )

    parsed = list(
        parse_information_table(artifacts.info_table_path, row.filed_at, on_error=on_row_error)
    )
    aggregated = list(aggregate_positions(parsed))
    cusips = [a.cusip for a in aggregated]

    if dry_run:
        return len(aggregated), rejects

    map_cusips(session, figi, cusips, run_id)

    filing = Filing(
        fund_id=fund.id,
        accession_no=row.accession_no,
        form_type=cover.form_type,
        period_of_report=cover.period_of_report,
        filed_at=row.filed_at,
        amendment_type=cover.amendment_type,
        raw_path=str(artifacts.info_table_path),
    )
    session.add(filing)
    session.flush()

    for agg in aggregated:
        sec_row = _get_or_create_security(session, agg.cusip)
        session.add(
            Position(
                filing_id=filing.id,
                security_id=sec_row.id,
                put_call=agg.put_call,
                shares=agg.shares,
                share_type=agg.share_type,
                value_usd=agg.value_usd,
            )
        )

    return len(aggregated), rejects


def run(
    *,
    quarters: int = 8,
    funds_filter: set[str] | None = None,
    force: bool = False,
    dry_run: bool = False,
    session: Session | None = None,
    sec: SecClient | None = None,
    figi: OpenFigiClient | None = None,
) -> dict[str, Any]:
    """Run the ETL pipeline. Any of session/sec/figi passed in are used
    verbatim; missing ones are constructed with production defaults."""
    stats: dict[str, Any] = {
        "funds": 0,
        "filings_loaded": 0,
        "filings_skipped": 0,
        "positions": 0,
        "rejects": 0,
    }

    owned_session = session is None
    owned_sec = sec is None
    owned_figi = figi is None
    session = session or SessionLocal()
    sec = sec or SecClient()
    figi = figi or OpenFigiClient()

    try:
        with _managed_run(session, dry_run) as run_row:
            run_id = run_row.id if run_row is not None else 0
            existing_accessions = set() if force else _existing_accessions(session)
            cutoff = _period_cutoff(quarters)

            for cik, name in _load_funds(FUNDS_YAML, funds_filter):
                stats["funds"] += 1
                fund = _upsert_fund(session, cik, name)
                if not dry_run:
                    session.commit()

                filings = sec.list_filings(cik)
                filings = [f for f in filings if f.period_of_report >= cutoff]

                for filing_row in filings:
                    if filing_row.accession_no in existing_accessions and not force:
                        stats["filings_skipped"] += 1
                        continue
                    try:
                        positions, rejects = _load_filing(
                            session, sec, figi, fund, filing_row, run_id, dry_run
                        )
                        stats["filings_loaded"] += 1
                        stats["positions"] += positions
                        stats["rejects"] += rejects
                        if not dry_run:
                            session.commit()
                    except Exception as e:
                        logger.exception(
                            "pipeline failed on %s / %s",
                            cik,
                            filing_row.accession_no,
                        )
                        if not dry_run:
                            session.rollback()
                            session.add(
                                EtlReject(
                                    run_id=run_id,
                                    source="pipeline",
                                    record={
                                        "cik": cik,
                                        "accession_no": filing_row.accession_no,
                                    },
                                    reason=str(e),
                                )
                            )
                            session.commit()
                        stats["rejects"] += 1

            if run_row is not None:
                run_row.finished_at = datetime.now(UTC)
                run_row.status = "ok"
                run_row.stats = stats
                session.commit()
    finally:
        if owned_figi:
            figi.close()
        if owned_sec:
            sec.close()
        if owned_session:
            session.close()

    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="concrisk.etl.pipeline")
    parser.add_argument(
        "--quarters",
        type=int,
        default=8,
        help="Number of past quarters to load (default: 8)",
    )
    parser.add_argument(
        "--fund",
        action="append",
        default=[],
        help="CIK to restrict to; repeat for multiple funds",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-parse filings already present in the DB",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk the pipeline without writing anything to the DB",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    stats = run(
        quarters=args.quarters,
        funds_filter=set(args.fund) if args.fund else None,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(f"pipeline done: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
