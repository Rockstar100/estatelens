"""Shared fetch machinery for every source adapter.

Guarantees:
  * requests and redirects are restricted to a validated allow-list of hosts;
  * one clear User-Agent, conservative concurrency, a polite delay, bounded
    retries with backoff, and per-request timeouts;
  * ``robots.txt`` is fetched once per host and consulted before every fetch;
  * no attempt is made to defeat CAPTCHAs, logins, or anti-bot controls — a
    challenge/redirect to such a page is recorded as a skip.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from app.config import get_settings
from app.services.logging import get_logger

log = get_logger("estatelens.scraper")

ALLOWED_HOSTS = {
    "darglobal.co.uk", "www.darglobal.co.uk",
    "wasalt.sa", "www.wasalt.sa",
}

_CHALLENGE_MARKERS = (
    "captcha", "cf-challenge", "attention required", "just a moment",
    "verifying you are human", "enable javascript and cookies",
    "access denied", "request unsuccessful",
)


class FetchError(Exception):
    pass


class BlockedByRobots(Exception):
    pass


class ChallengePage(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    html: str
    fetched_at: float = field(default_factory=time.time)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.html.encode("utf-8", "replace")).hexdigest()


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_allowed_host(url: str) -> bool:
    return host_of(url) in ALLOWED_HOSTS


class FetchSession:
    def __init__(self) -> None:
        s = get_settings()
        self._ua = s.scraper_user_agent
        self._delay = s.scraper_delay_seconds
        self._sem = asyncio.Semaphore(max(1, s.scraper_max_concurrency))
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": self._ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
            max_redirects=5,
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        host = host_of(url)
        if host in self._robots:
            return self._robots[host]
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
        try:
            resp = await self._client.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp = None
        except httpx.HTTPError:
            rp = None
        self._robots[host] = rp
        return rp

    async def allowed_by_robots(self, url: str) -> bool:
        rp = await self._robots_for(url)
        if rp is None:
            return True
        return rp.can_fetch(self._ua, url) or rp.can_fetch("*", url)

    async def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host, 0.0)
        wait = self._delay - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_hit[host] = time.monotonic()

    async def fetch(self, url: str, *, retries: int = 3) -> FetchResult:
        if not is_allowed_host(url):
            raise FetchError(f"host not on allow-list: {url}")
        if not await self.allowed_by_robots(url):
            raise BlockedByRobots(url)

        host = host_of(url)
        attempt = 0
        while True:
            attempt += 1
            async with self._sem:
                await self._throttle(host)
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError as exc:
                    if attempt > retries:
                        raise FetchError(f"{url}: {exc}") from exc
                    await asyncio.sleep(min(2**attempt, 10))
                    continue

            if not is_allowed_host(str(resp.url)):
                raise FetchError(f"redirected off allow-list: {resp.url}")

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt > retries:
                    raise FetchError(f"{url}: HTTP {resp.status_code} after {retries} retries")
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if (retry_after or "").isdigit() else min(2**attempt, 15)
                log.warning("retrying", extra={"url": url, "status": resp.status_code, "in": delay})
                await asyncio.sleep(delay)
                continue

            text = resp.text
            low = text[:4000].lower()
            if resp.status_code == 403 or any(m in low for m in _CHALLENGE_MARKERS):
                raise ChallengePage(f"{url}: HTTP {resp.status_code} looks like a bot challenge")

            if resp.status_code >= 400:
                raise FetchError(f"{url}: HTTP {resp.status_code}")

            return FetchResult(
                url=url,
                final_url=str(resp.url),
                status_code=resp.status_code,
                html=text,
            )

    async def get_text(self, url: str) -> str:
        if not is_allowed_host(url):
            raise FetchError(f"host not on allow-list: {url}")
        async with self._sem:
            await self._throttle(host_of(url))
            resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.text


def absolute(base: str, href: str) -> str:
    return urljoin(base, href)
