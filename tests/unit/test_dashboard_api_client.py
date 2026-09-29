from collections.abc import Callable

import httpx
import pytest
from dashboard.api_client import _raw_get


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_get_hits_base_url_and_returns_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONCRISK_API_URL", "http://api.local")
    monkeypatch.setenv("API_KEY", "")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"funds": []})

    body = _raw_get("/funds", client=_client(handler))

    assert seen == ["http://api.local/funds"]
    assert body == {"funds": []}


def test_get_strips_trailing_slash_from_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONCRISK_API_URL", "http://api.local/")
    monkeypatch.setenv("API_KEY", "")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    _raw_get("/funds", client=_client(handler))

    assert seen == ["http://api.local/funds"]  # not '.local//funds'


def test_get_sends_apikey_header_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONCRISK_API_URL", "http://api.local")
    monkeypatch.setenv("API_KEY", "shhh-secret")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-API-Key"))
        return httpx.Response(200, json={})

    _raw_get("/funds", client=_client(handler))

    assert seen == ["shhh-secret"]


def test_get_omits_apikey_header_when_env_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONCRISK_API_URL", "http://api.local")
    monkeypatch.setenv("API_KEY", "")
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-API-Key"))
        return httpx.Response(200, json={})

    _raw_get("/funds", client=_client(handler))

    assert seen == [None]


def test_get_forwards_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONCRISK_API_URL", "http://api.local")
    monkeypatch.setenv("API_KEY", "")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    _raw_get("/breaches", params={"severity": "warning"}, client=_client(handler))

    assert seen == ["http://api.local/breaches?severity=warning"]


def test_get_raises_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONCRISK_API_URL", "http://api.local")
    monkeypatch.setenv("API_KEY", "")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(httpx.HTTPStatusError):
        _raw_get("/funds/99/quarters", client=_client(handler))
