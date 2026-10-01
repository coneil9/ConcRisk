import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from concrisk.api.auth import require_api_key
from concrisk.api.routers import breaches as breaches_router
from concrisk.api.routers import compare as compare_router
from concrisk.api.routers import exposure as exposure_router
from concrisk.api.routers import funds as funds_router
from concrisk.db.session import SessionLocal

logger = logging.getLogger(__name__)

app = FastAPI(title="ConcRisk API")

# Dashboard and API live on different Container App FQDNs in prod, so
# the dashboard's browser-side fetches hit this API cross-origin.
# `allow_origins=["*"]` is MVP-grade — tighten to the dashboard FQDN
# once you have it. X-API-Key auth still gates every data route.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["X-API-Key", "Content-Type"],
)


@app.get("/health")
def health() -> JSONResponse:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health check: database unreachable")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "unreachable"},
        )
    return JSONResponse(content={"status": "ok", "db": "ok"})


_auth_dep = [Depends(require_api_key)]
app.include_router(funds_router.router, dependencies=_auth_dep)
app.include_router(exposure_router.router, dependencies=_auth_dep)
app.include_router(breaches_router.router, dependencies=_auth_dep)
app.include_router(compare_router.router, dependencies=_auth_dep)
