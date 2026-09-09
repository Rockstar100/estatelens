"""FastAPI application: serves the JSON API under /api and the built SPA elsewhere."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import chat, health, properties, sources
from app.api.deps import api_limiter, client_key
from app.config import get_settings
from app.db import client as db_client
from app.db.indexes import ensure_indexes
from app.services.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger("estatelens.app")

# frontend/dist is copied next to the backend package in the Docker image; in dev
# it sits at repo_root/frontend/dist.
_HERE = Path(__file__).resolve()
_STATIC_CANDIDATES = [
    _HERE.parent.parent / "static",
    _HERE.parent.parent.parent / "frontend" / "dist",
]
STATIC_DIR = next((p for p in _STATIC_CANDIDATES if (p / "index.html").exists()), None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_client.connect(settings)
    try:
        await ensure_indexes()
        log.info("startup: mongo connected, indexes ensured")
    except Exception as exc:  # noqa: BLE001
        log.warning("startup: index creation deferred", extra={"error": str(exc)})
    yield
    await db_client.disconnect()


app = FastAPI(
    title="EstateLens API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-Id"],
)


_RATE_LIMIT_EXEMPT = (
    "/api/health",
    "/api/readiness",
    "/api/docs",
    "/api/openapi.json",
)


@app.middleware("http")
async def _rate_limit_mw(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(_RATE_LIMIT_EXEMPT):
        allowed, retry_after = api_limiter.check(client_key(request))
        if not allowed:
            return JSONResponse(
                {"detail": "Too many requests."},
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    return await call_next(request)


app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(properties.router, prefix="/api")
app.include_router(sources.router, prefix="/api")


@app.get("/api")
async def api_root() -> dict:
    return {"name": "EstateLens API", "version": __version__, "docs": "/api/docs"}


if STATIC_DIR is not None:
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    async def no_frontend() -> dict:
        return {
            "name": "EstateLens API",
            "version": __version__,
            "note": "Frontend build not found. Run `npm run build` in frontend/.",
            "docs": "/api/docs",
        }
