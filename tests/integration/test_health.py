import pytest
from fastapi.testclient import TestClient

from concrisk.api.main import app


@pytest.mark.integration
def test_health_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
