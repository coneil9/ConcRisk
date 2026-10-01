from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from concrisk.db.models import EtfConstituent, Security


def load_latest_constituents(
    session: Session, *, as_of_cutoff: date | None = None
) -> dict[str, list[tuple[str, float]]]:
    """Return `{etf_ticker: [(constituent_ticker, weight), ...]}` keyed by
    the ETF ticker, using the latest `as_of` ≤ `as_of_cutoff` per ETF.

    `as_of_cutoff=None` → use the latest snapshot for each ETF regardless
    of date. SPEC §6.6 requires "closest to (not after) the filing's
    period_of_report"; callers pass the fund-quarter's period.
    """
    # Find the latest as_of per etf_security_id subject to the cutoff.
    subq = select(
        EtfConstituent.etf_security_id,
        func.max(EtfConstituent.as_of).label("latest_as_of"),
    )
    if as_of_cutoff is not None:
        subq = subq.where(EtfConstituent.as_of <= as_of_cutoff)
    subq = subq.group_by(EtfConstituent.etf_security_id).subquery()

    stmt = (
        select(
            Security.ticker,
            EtfConstituent.constituent_ticker,
            EtfConstituent.weight,
        )
        .join(
            subq,
            (subq.c.etf_security_id == EtfConstituent.etf_security_id)
            & (subq.c.latest_as_of == EtfConstituent.as_of),
        )
        .join(Security, Security.id == EtfConstituent.etf_security_id)
    )

    out: dict[str, list[tuple[str, float]]] = {}
    for etf_ticker, con_ticker, weight in session.execute(stmt).all():
        if not etf_ticker or not con_ticker:
            continue
        out.setdefault(str(etf_ticker).upper(), []).append(
            (str(con_ticker).upper(), float(weight))
        )
    return out
