from typing import Annotated

from fastapi import Header, HTTPException, status

from concrisk.config import get_settings


def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency: enforce `X-API-Key` header when
    `settings.api_key` is set. Empty key = auth disabled (dev mode).
    /health should register without this dep."""
    key = get_settings().api_key
    if not key:
        return
    if x_api_key != key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-API-Key",
        )
