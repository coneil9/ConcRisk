import pytest
from pydantic import ValidationError

from concrisk.config import Settings, get_settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    monkeypatch.setenv("ENV", "dev")

    settings = get_settings()

    assert settings.env == "dev"
    assert str(settings.database_url).startswith("postgresql")


def test_settings_fail_fast_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "database_url" in str(excinfo.value).lower()
