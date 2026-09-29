from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from concrisk.api.main import app
from concrisk.config import get_settings
from concrisk.db.session import get_session

pytestmark = pytest.mark.integration


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_no_auth_required_when_api_key_empty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEY", "")
    get_settings.cache_clear()
    r = client.get("/funds")
    assert r.status_code == 200


def test_auth_required_when_api_key_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEY", "shhh-secret")
    get_settings.cache_clear()
    r = client.get("/funds")
    assert r.status_code == 401


def test_wrong_api_key_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "shhh-secret")
    get_settings.cache_clear()
    r = client.get("/funds", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_correct_api_key_accepted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "shhh-secret")
    get_settings.cache_clear()
    r = client.get("/funds", headers={"X-API-Key": "shhh-secret"})
    assert r.status_code == 200


def test_health_bypasses_auth_when_key_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEY", "shhh-secret")
    get_settings.cache_clear()
    r = client.get("/health")
    assert r.status_code == 200
