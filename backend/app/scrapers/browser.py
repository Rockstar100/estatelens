"""Browser-rendered fetching for Incapsula/Cloudflare-fronted public pages.

DarGlobal fronts its public project pages with an Imperva Incapsula JavaScript
challenge; a few Wasalt informational pages are client-rendered. A real browser
(Crawl4AI + Chromium, ``magic`` / ``simulate_user`` mode) clears those the way
any visitor would. We do NOT solve CAPTCHAs or defeat a hard block — a page that
still looks like a challenge after rendering is reported as such and skipped,
never fabricated.

**Each render runs in its own short-lived subprocess** (``_fetch_worker``). On
this platform a wedged Playwright call ignores ``asyncio`` cancellation, so an
in-process timeout cannot free it; a subprocess can simply be SIGKILLed on
timeout while everything already collected is kept. This is slower per page but
never hangs the crawl.

Crawl4AI is an optional dependency (``requirements-ingest.txt``) and is not part
of the deployed web image, so the import is guarded.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.scrapers.base import ALLOWED_HOSTS, host_of

# backend/ dir, so the worker subprocess can `import app` regardless of how the
# CLI was launched.
_BACKEND_DIR = str(Path(__file__).resolve().parents[2])

try:  # pragma: no cover - ingestion environment only
    import crawl4ai  # noqa: F401

    CRAWL4AI_AVAILABLE = True
except Exception:  # noqa: BLE001
    CRAWL4AI_AVAILABLE = False

PLAYWRIGHT_AVAILABLE = CRAWL4AI_AVAILABLE

_CHALLENGE_MARKERS = (
    "incapsula incident",
    "request unsuccessful",
    "just a moment",
    "verifying you are human",
    "attention required",
    "enable javascript and cookies to continue",
    "checking your browser before",
    "hanya sebentar",
)

_PER_PAGE_TIMEOUT = 75.0


@dataclass
class RenderedPage:
    url: str
    final_url: str
    status_code: int
    html: str
    title: str = ""
    ok: bool = False
    error: str | None = None

    @property
    def looks_like_challenge(self) -> bool:
        low = self.html[:6000].lower()
        return any(m in low for m in _CHALLENGE_MARKERS) or len(self.html) < 2500


class BrowserFetcher:
    """Async context manager kept for API compatibility; each ``fetch`` spawns a
    worker subprocess, so there is no shared browser to open or close."""

    def __init__(self, *, concurrency: int | None = None, settle_seconds: float = 6.0) -> None:
        if not CRAWL4AI_AVAILABLE:
            raise RuntimeError(
                "crawl4ai is not installed. Install with:\n"
                "  pip install -r backend/requirements-ingest.txt\n"
                "  python -m playwright install chromium"
            )

    async def __aenter__(self) -> "BrowserFetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self, url: str) -> RenderedPage:
        if host_of(url) not in ALLOWED_HOSTS:
            return RenderedPage(url, url, 0, "", ok=False, error="host not on allow-list")

        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = _BACKEND_DIR + (os.pathsep + existing if existing else "")
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.scrapers._fetch_worker",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=_BACKEND_DIR,
            env=env,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_PER_PAGE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            return RenderedPage(url, url, 0, "", ok=False, error="render budget exceeded (killed)")

        try:
            data = json.loads(stdout.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            return RenderedPage(url, url, 0, "", ok=False, error="worker produced no JSON")

        html = data.get("html") or ""
        final_url = data.get("final_url") or url
        if host_of(final_url) not in ALLOWED_HOSTS:
            return RenderedPage(url, final_url, 0, "", ok=False, error="redirected off allow-list")

        page = RenderedPage(
            url=url,
            final_url=final_url,
            status_code=int(data.get("status") or 0),
            html=html,
            title=data.get("title") or "",
            ok=bool(html) and len(html) > 2500,
            error=data.get("error"),
        )
        if page.looks_like_challenge:
            page.ok = False
            page.error = page.error or "bot challenge / near-empty page"
        return page

    async def fetch_many(self, urls: list[str]) -> list[RenderedPage]:
        out: list[RenderedPage] = []
        for u in urls:
            if host_of(u) in ALLOWED_HOSTS:
                out.append(await self.fetch(u))
        return out
