"""Liveness and readiness. Neither consumes model quota."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response

from app import __version__
from app.config import get_settings
from app.db import client as db_client
from app.db import repo
from app.models.api import HealthResponse, ReadinessCheck, ReadinessResponse

router = APIRouter(tags=["health"])


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=__version__, time=datetime.now(timezone.utc))


@router.api_route("/readiness", methods=["GET", "HEAD"], response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    settings = get_settings()
    checks: list[ReadinessCheck] = []

    try:
        await db_client.ping()
        host = db_client.mongo_host()
        checks.append(ReadinessCheck(name="mongodb", ok=True, detail=f"reachable ({host})"))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadinessCheck(name="mongodb", ok=False, detail=f"unreachable: {exc}"))

    checks.append(
        ReadinessCheck(
            name="llm_config",
            ok=settings.llm_configured,
            detail=(
                f"active={settings.active_llm_label}; "
                f"groq={'yes' if settings.groq_api_key else 'no'}, "
                f"gemini={'yes' if settings.gemini_api_key else 'no'}, "
                f"openrouter={'yes' if settings.openrouter_api_key else 'no'}"
            ),
        )
    )

    try:
        counts = await repo.collection_counts()
        has_data = counts["properties"] > 0 and counts["passages"] > 0
        checks.append(
            ReadinessCheck(
                name="indexed_data",
                ok=has_data,
                detail=f"{counts['properties']} properties, {counts['passages']} active passages",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadinessCheck(name="indexed_data", ok=False, detail=str(exc)))

    ready = all(c.ok for c in checks)
    if not ready:
        response.status_code = 503
    return ReadinessResponse(ready=ready, checks=checks, time=datetime.now(timezone.utc))
