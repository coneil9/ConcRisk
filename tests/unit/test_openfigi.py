from collections.abc import Callable

import httpx
import pytest

from concrisk.etl.openfigi import OpenFigiClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_batch_size_uses_no_key_limit_when_key_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "")
    with OpenFigiClient(client=_client(lambda _: httpx.Response(200))) as figi:
        assert figi.batch_size == 10  # OpenFIGI free-tier cap as of 2026-09


def test_batch_size_uses_keyed_limit_when_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "some-key")
    with OpenFigiClient(client=_client(lambda _: httpx.Response(200))) as figi:
        assert figi.batch_size == 100


def test_resolve_cusips_batch_maps_first_valid_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "data": [
                        {
                            "figi": "BBG000B9XRY4",
                            "ticker": "AAPL",
                            "name": "APPLE INC",
                            "securityType": "Common Stock",
                            "exchCode": "US",
                        }
                    ]
                },
                {"data": []},
            ],
        )

    with OpenFigiClient(client=_client(handler)) as figi:
        out = figi.resolve_cusips_batch(["037833100", "999999999"])

    assert out["037833100"] is not None
    assert out["037833100"].ticker == "AAPL"
    assert out["037833100"].figi == "BBG000B9XRY4"
    assert out["999999999"] is None


def test_resolve_cusips_batch_rejects_oversized_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "")
    with (
        OpenFigiClient(client=_client(lambda _: httpx.Response(200))) as figi,
        pytest.raises(ValueError, match="exceeds limit"),
    ):
        figi.resolve_cusips_batch(["c"] * 11)


def test_apikey_header_sent_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "my-key")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-OPENFIGI-APIKEY"))
        return httpx.Response(200, json=[{"data": []}])

    with OpenFigiClient(client=_client(handler)) as figi:
        figi.resolve_cusips_batch(["c1"])

    assert seen == ["my-key"]


def test_apikey_header_absent_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFIGI_API_KEY", "")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-OPENFIGI-APIKEY"))
        return httpx.Response(200, json=[{"data": []}])

    with OpenFigiClient(client=_client(handler)) as figi:
        figi.resolve_cusips_batch(["c1"])

    assert seen == [None]
