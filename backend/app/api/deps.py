"""Shared API dependencies: request id, rate limiting."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request

from app.config import get_settings
from app.services.rate_limit import SlidingWindowLimiter

_settings = get_settings()
# Rebuild limiters from current settings (import-time snapshot is fine for demo;
# restart the process after changing RATE_LIMIT_* env vars).
chat_limiter = SlidingWindowLimiter(_settings.rate_limit_chat_per_minute)
api_limiter = SlidingWindowLimiter(_settings.rate_limit_api_per_minute)


def reset_rate_limiters() -> None:
    chat_limiter.reset()
    api_limiter.reset()


def client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return ip


def request_id(request: Request) -> str:
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    return rid


def enforce_api_rate_limit(request: Request) -> None:
    allowed, retry_after = api_limiter.check(client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def enforce_chat_rate_limit(request: Request) -> tuple[bool, float]:
    return chat_limiter.check(client_key(request))
