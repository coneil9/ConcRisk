import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

from concrisk.config import get_settings

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_HOST = "https://data.sec.gov"
SEC_ARCHIVES_HOST = "https://www.sec.gov"
DEFAULT_MAX_REQ_PER_SEC = 8.0
DEFAULT_RETRIES = 3
FORM_TYPES = frozenset({"13F-HR", "13F-HR/A"})


@dataclass(frozen=True)
class SubmissionRow:
    accession_no: str
    form_type: str
    filed_at: date
    period_of_report: date
    primary_document: str


@dataclass(frozen=True)
class FilingArtifacts:
    cover_path: Path
    info_table_path: Path


class _TokenBucket:
    """Process-global rate limiter. Simple leaky-bucket, thread-safe."""

    def __init__(self, rate_per_sec: float) -> None:
        self._rate = rate_per_sec
        self._tokens = rate_per_sec
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens < 1:
                needed = (1 - self._tokens) / self._rate
                time.sleep(needed)
                self._tokens = 0.0
                self._last = time.monotonic()
            else:
                self._tokens -= 1


class SecClient:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        max_req_per_sec: float = DEFAULT_MAX_REQ_PER_SEC,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.sec_user_agent:
            raise RuntimeError("SEC_USER_AGENT must be set in .env before calling SEC EDGAR.")
        self._user_agent = settings.sec_user_agent
        self._cache_dir = cache_dir or Path("data/raw/sec")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._bucket = _TokenBucket(max_req_per_sec)
        self._client = client or httpx.Client(
            headers={
                "User-Agent": self._user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=httpx.Timeout(30.0),
        )

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

    def list_filings(self, cik: str) -> list[SubmissionRow]:
        cik_padded = cik.zfill(10)
        url = f"{SEC_SUBMISSIONS_HOST}/submissions/CIK{cik_padded}.json"
        data = self._get(url).json()
        recent = data["filings"]["recent"]
        rows: list[SubmissionRow] = []
        for accession, form, filed_str, period_str, primary in zip(
            recent["accessionNumber"],
            recent["form"],
            recent["filingDate"],
            recent["reportDate"],
            recent["primaryDocument"],
            strict=True,
        ):
            if form not in FORM_TYPES:
                continue
            if not period_str:
                logger.warning("sec skip %s: no reportDate", accession)
                continue
            rows.append(
                SubmissionRow(
                    accession_no=accession,
                    form_type=form,
                    filed_at=date.fromisoformat(filed_str),
                    period_of_report=date.fromisoformat(period_str),
                    primary_document=primary,
                )
            )
        return rows

    def fetch_filing(self, cik: str, accession_no: str) -> FilingArtifacts:
        cik_int = str(int(cik))
        acc_nodash = accession_no.replace("-", "")
        base_url = f"{SEC_ARCHIVES_HOST}/Archives/edgar/data/{cik_int}/{acc_nodash}"
        local_dir = self._cache_dir / cik.zfill(10) / accession_no
        local_dir.mkdir(parents=True, exist_ok=True)

        index_local = local_dir / "index.json"
        index = self._cached_json(f"{base_url}/index.json", index_local)
        xml_names = [f["name"] for f in index["directory"]["item"] if f["name"].endswith(".xml")]
        if "primary_doc.xml" not in xml_names:
            raise RuntimeError(f"no primary_doc.xml in {accession_no}")

        cover_local = local_dir / "primary_doc.xml"
        self._cached_download(f"{base_url}/primary_doc.xml", cover_local)

        info_candidates = [n for n in xml_names if n != "primary_doc.xml"]
        if not info_candidates:
            raise RuntimeError(f"no info-table XML in {accession_no}")
        info_name = next(
            (n for n in info_candidates if "info" in n.lower() or n.startswith("form13f")),
            info_candidates[0],
        )
        info_local = local_dir / info_name
        self._cached_download(f"{base_url}/{info_name}", info_local)

        return FilingArtifacts(cover_path=cover_local, info_table_path=info_local)

    def _get(self, url: str) -> httpx.Response:
        headers = {"User-Agent": self._user_agent}
        last_error: Exception | None = None
        for attempt in range(DEFAULT_RETRIES):
            self._bucket.acquire()
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.TransportError as e:
                last_error = e
                sleep_for = 2**attempt
                logger.warning("sec %s transport error %s; retrying in %ds", url, e, sleep_for)
                time.sleep(sleep_for)
                continue
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                sleep_for = 2**attempt
                logger.warning("sec %s -> %d; retrying in %ds", url, resp.status_code, sleep_for)
                time.sleep(sleep_for)
                continue
            resp.raise_for_status()
            return resp
        if last_error is not None:
            raise last_error
        resp.raise_for_status()
        return resp

    def _cached_json(self, url: str, local: Path) -> dict[str, Any]:
        if local.exists():
            return json.loads(local.read_bytes())
        resp = self._get(url)
        local.write_bytes(resp.content)
        return resp.json()

    def _cached_download(self, url: str, local: Path) -> None:
        if local.exists():
            logger.debug("sec cache hit: %s", local)
            return
        resp = self._get(url)
        local.write_bytes(resp.content)
        logger.info("sec fetched: %s (%d bytes)", local, len(resp.content))
