import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from concrisk.config import get_settings
from concrisk.db.models import EtlReject, Security

logger = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# API limits (OpenFIGI docs):
#   no key : 25 jobs per request, 25 requests per 6 s
#   with key: 100 jobs per request, 250 requests per 6 s
_LIMITS_WITH_KEY = (100, 250 / 6.0)
_LIMITS_NO_KEY = (25, 25 / 6.0)


@dataclass(frozen=True)
class SecurityMapping:
    cusip: str
    figi: str | None
    ticker: str | None
    name: str | None
    security_type: str | None
    exch_code: str | None


class OpenFigiClient:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.openfigi_api_key or None
        self._batch_size, self._max_rps = _LIMITS_WITH_KEY if self._api_key else _LIMITS_NO_KEY
        self._client = client or httpx.Client(
            headers={"Content-Type": "application/json"}, timeout=httpx.Timeout(30.0)
        )
        self._min_interval = 1.0 / self._max_rps
        self._last_call: float = 0.0

    @property
    def batch_size(self) -> int:
        return self._batch_size

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def resolve_cusips_batch(self, cusips: list[str]) -> dict[str, SecurityMapping | None]:
        """One HTTP call. `cusips` must be no larger than `batch_size`.
        Returns a dict with every input cusip; unresolved ones map to None."""
        if len(cusips) > self._batch_size:
            raise ValueError(f"batch of {len(cusips)} exceeds limit {self._batch_size}")
        if not cusips:
            return {}

        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
        headers = {"X-OPENFIGI-APIKEY": self._api_key} if self._api_key else None
        self._throttle()
        resp = self._client.post(OPENFIGI_URL, content=json.dumps(payload), headers=headers)
        # 429 retry, once
        if resp.status_code == 429:
            logger.warning("openfigi 429; sleeping 6s and retrying")
            time.sleep(6.0)
            self._throttle()
            resp = self._client.post(OPENFIGI_URL, content=json.dumps(payload), headers=headers)
        resp.raise_for_status()
        body = resp.json()

        out: dict[str, SecurityMapping | None] = {}
        for cusip, result in zip(cusips, body, strict=True):
            first = _first_valid(result.get("data") or []) if isinstance(result, dict) else None
            if first is None:
                out[cusip] = None
                continue
            out[cusip] = SecurityMapping(
                cusip=cusip,
                figi=first.get("figi"),
                ticker=first.get("ticker"),
                name=first.get("name"),
                security_type=first.get("securityType") or first.get("securityType2"),
                exch_code=first.get("exchCode"),
            )
        return out

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()


def _first_valid(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("figi"):
            return entry
    return None


def load_cached_mappings(
    session: Session, cusips: Iterable[str]
) -> dict[str, SecurityMapping | None]:
    """Read already-resolved CUSIPs (mapped_at IS NOT NULL) from securities."""
    cusip_list = list({c for c in cusips if c})
    if not cusip_list:
        return {}
    rows = (
        session.execute(
            select(Security).where(Security.cusip.in_(cusip_list), Security.mapped_at.is_not(None))
        )
        .scalars()
        .all()
    )
    return {
        r.cusip: SecurityMapping(
            cusip=r.cusip,
            figi=r.figi,
            ticker=r.ticker,
            name=r.name,
            security_type=r.security_type,
            exch_code=r.exch_code,
        )
        if r.figi
        else None
        for r in rows
    }


def upsert_mappings(
    session: Session,
    mappings: dict[str, SecurityMapping | None],
    run_id: int,
) -> None:
    """Insert or update securities rows for every cusip in mappings.
    Unresolved cusips get a row with mapped_at set but null mapping
    fields, so we won't retry them on the next pipeline run. Rejects
    are logged to etl_rejects."""
    now = datetime.now(UTC)
    existing = {
        r.cusip: r
        for r in session.execute(select(Security).where(Security.cusip.in_(list(mappings.keys()))))
        .scalars()
        .all()
    }
    for cusip, mapping in mappings.items():
        sec = existing.get(cusip)
        if sec is None:
            sec = Security(cusip=cusip)
            session.add(sec)
        if mapping is None:
            sec.mapped_at = now
            session.add(
                EtlReject(
                    run_id=run_id,
                    source="openfigi",
                    record={"cusip": cusip},
                    reason="no OpenFIGI match",
                )
            )
        else:
            sec.figi = mapping.figi
            sec.ticker = mapping.ticker
            sec.name = mapping.name
            sec.security_type = mapping.security_type
            sec.exch_code = mapping.exch_code
            sec.mapped_at = now


def map_cusips(
    session: Session,
    client: OpenFigiClient,
    cusips: Iterable[str],
    run_id: int,
) -> dict[str, SecurityMapping | None]:
    """Cache-first resolution: return cached results untouched; only send
    unresolved CUSIPs to OpenFIGI. Upsert everything into securities."""
    unique = list({c for c in cusips if c})
    cached = load_cached_mappings(session, unique)
    remaining = [c for c in unique if c not in cached]

    new_results: dict[str, SecurityMapping | None] = {}
    for i in range(0, len(remaining), client.batch_size):
        chunk = remaining[i : i + client.batch_size]
        new_results.update(client.resolve_cusips_batch(chunk))

    if new_results:
        upsert_mappings(session, new_results, run_id)

    return {**cached, **new_results}
