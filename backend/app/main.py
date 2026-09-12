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
        log.info(
            "startup: mongo connected, indexes ensured",
            extra={"host": db_client.mongo_host(), "database": settings.mongodb_database},
        )
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
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-Id"],
)


_RATE_LIMIT_EXEMPT = (
    "/api/health",
    "/api/readiness",
    "/api/docs",
    "/api/openapi.json",
)


def _is_rate_limit_exempt(path: str) -> bool:
    if path in _RATE_LIMIT_EXEMPT:
        return True
    # Property photo thumbs are requested many-at-a-time by the SPA.
    return path.startswith("/api/properties/") and path.endswith("/image")



# A tight CSP: the SPA is fully self-hosted (no CDN, no inline scripts after the
# Vite build), talks only to its own origin, and is never meant to be framed.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.middleware("http")
async def _security_and_rate_limit_mw(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not _is_rate_limit_exempt(path):
        allowed, retry_after = api_limiter.check(client_key(request))
        if not allowed:
            return JSONResponse(
                {"detail": "Too many requests."},
                status_code=429,
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    # CSP only on document responses (not JSON/SSE), to keep it simple.
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        response.headers.setdefault("Content-Security-Policy", _CSP)
    return response


app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(properties.router, prefix="/api")
app.include_router(sources.router, prefix="/api")


@app.get("/api")
async def api_root() -> dict:
    return {"name": "EstateLens API", "version": __version__, "docs": "/api/docs"}


if STATIC_DIR is not None:
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.api_route("/", methods=["GET", "HEAD"])
    async def no_frontend() -> dict:
        return {
            "name": "EstateLens API",
            "version": __version__,
            "note": "Frontend build not found. Run `npm run build` in frontend/.",
            "docs": "/api/docs",
        }
