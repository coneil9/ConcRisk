from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from concrisk.etl.sec_client import SecClient, _TokenBucket

USER_AGENT = "Test User test@example.com"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_missing_user_agent_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "")
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        SecClient(cache_dir=tmp_path, client=_client(lambda _: httpx.Response(200)))


def test_user_agent_sent_on_every_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("User-Agent"))
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "accessionNumber": [],
                        "form": [],
                        "filingDate": [],
                        "reportDate": [],
                        "primaryDocument": [],
                    }
                }
            },
        )

    with SecClient(cache_dir=tmp_path, client=_client(handler)) as sec:
        sec.list_filings("1067983")

    assert seen == [USER_AGENT]


def test_list_filings_filters_form_types(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "CIK0001067983.json" in request.url.path
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "accessionNumber": ["A1", "A2", "A3", "A4"],
                        "form": ["13F-HR", "10-K", "13F-HR/A", "13F-NT"],
                        "filingDate": [
                            "2024-11-14",
                            "2024-03-01",
                            "2024-05-15",
                            "2024-02-14",
                        ],
                        "reportDate": [
                            "2024-09-30",
                            "2023-12-31",
                            "2024-03-31",
                            "2023-12-31",
                        ],
                        "primaryDocument": [
                            "primary_doc.xml",
                            "10k.htm",
                            "primary_doc.xml",
                            "primary_doc.xml",
                        ],
                    }
                }
            },
        )

    with SecClient(cache_dir=tmp_path, client=_client(handler)) as sec:
        rows = sec.list_filings("1067983")

    assert [r.accession_no for r in rows] == ["A1", "A3"]
    assert rows[0].form_type == "13F-HR"
    assert rows[0].period_of_report == date(2024, 9, 30)
    assert rows[1].form_type == "13F-HR/A"


def test_filing_cache_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        url = str(request.url)
        if url.endswith("/index.json"):
            return httpx.Response(
                200,
                json={
                    "directory": {
                        "item": [
                            {"name": "primary_doc.xml", "size": 100},
                            {"name": "form13fInfoTable.xml", "size": 200},
                        ]
                    }
                },
            )
        if url.endswith("/primary_doc.xml"):
            return httpx.Response(200, content=b"<cover/>")
        if url.endswith("/form13fInfoTable.xml"):
            return httpx.Response(200, content=b"<informationTable/>")
        return httpx.Response(404)

    with SecClient(cache_dir=tmp_path, client=_client(handler)) as sec:
        sec.fetch_filing("0001067983", "0000950123-25-005701")
        first = call_count
        sec.fetch_filing("0001067983", "0000950123-25-005701")

    # First fetch: 3 HTTP calls (index + cover + info table).
    # Second fetch: 0 HTTP calls — everything served from disk cache.
    assert first == 3
    assert call_count == 3


def test_retry_on_500_then_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", USER_AGENT)
    monkeypatch.setattr("time.sleep", lambda _s: None)  # skip real backoff
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "accessionNumber": [],
                        "form": [],
                        "filingDate": [],
                        "reportDate": [],
                        "primaryDocument": [],
                    }
                }
            },
        )

    with SecClient(cache_dir=tmp_path, client=_client(handler)) as sec:
        sec.list_filings("1067983")

    assert calls["n"] == 2


def test_token_bucket_sleeps_when_exceeding_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_now = [0.0]
    slept: list[float] = []

    def _monotonic() -> float:
        return fake_now[0]

    def _sleep(seconds: float) -> None:
        slept.append(seconds)
        fake_now[0] += seconds

    monkeypatch.setattr("concrisk.etl.sec_client.time.monotonic", _monotonic)
    monkeypatch.setattr("concrisk.etl.sec_client.time.sleep", _sleep)

    bucket = _TokenBucket(rate_per_sec=4.0)
    # Drain the initial 4 tokens without advancing time. The 5th call must sleep.
    for _ in range(4):
        bucket.acquire()
    assert slept == []

    bucket.acquire()
    assert len(slept) == 1
    assert slept[0] == pytest.approx(0.25)  # 1 / 4 tokens per second
