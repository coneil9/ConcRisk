import logging

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from concrisk.api.auth import require_api_key
from concrisk.api.routers import funds as funds_router
from concrisk.db.session import SessionLocal

logger = logging.getLogger(__name__)

app = FastAPI(title="ConcRisk API")


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


app.include_router(funds_router.router, dependencies=[Depends(require_api_key)])
