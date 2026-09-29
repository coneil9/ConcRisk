import os
from typing import Any

import httpx
import streamlit as st

DEFAULT_BASE_URL = "http://localhost:8000"


def _base_url() -> str:
    return os.environ.get("CONCRISK_API_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    return os.environ.get("API_KEY", "")


def _raw_get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Uncached HTTP GET. Reads CONCRISK_API_URL and API_KEY from env
    (not concrisk.config) — the dashboard is a separate process from
    the API and mustn't share the Pydantic settings singleton.

    Pass `client` to inject a mocked transport for tests."""
    key = _api_key()
    headers = {"X-API-Key": key} if key else {}
    url = f"{_base_url()}{path}"
    if client is None:
        with httpx.Client(timeout=30.0) as c:
            resp = c.get(url, params=params, headers=headers)
    else:
        resp = client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=60, show_spinner=False)
def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cached HTTP GET (TTL 60s). Wrapper used by all pages."""
    return _raw_get(path, params)


def clear_cache() -> None:
    """Manually bust the cache — useful for a 'refresh' button."""
    get.clear()
