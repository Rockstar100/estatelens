"""One-shot page renderer, run as a short-lived subprocess.

    python -m app.scrapers._fetch_worker <url>

Renders a single URL with Crawl4AI and writes a JSON blob
``{"final_url","status","title","html"}`` to stdout. Running each render in its
own process is the only reliable way to bound a stuck Playwright call on this
platform — the parent SIGKILLs the child on timeout and moves on, losing nothing
already collected.
"""

from __future__ import annotations

import asyncio
import json
import sys


async def _run(url: str) -> dict:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    browser_cfg = BrowserConfig(
        headless=True,
        user_agent=ua,
        viewport_width=1366,
        viewport_height=900,
        light_mode=True,
        verbose=False,
        extra_args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=40_000,
        wait_until="domcontentloaded",
        delay_before_return_html=6.0,
        simulate_user=True,
        magic=True,
        wait_for_images=False,
        scan_full_page=False,
        remove_overlay_elements=True,
        word_count_threshold=3,
        verbose=False,
    )
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=url, config=run_cfg)
    meta = getattr(result, "metadata", None) or {}
    return {
        "final_url": getattr(result, "url", url) or url,
        "status": getattr(result, "status_code", None)
        or (200 if getattr(result, "success", False) else 0),
        "title": meta.get("title") or "",
        "html": getattr(result, "html", "") or "",
        "error": getattr(result, "error_message", None),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: _fetch_worker <url>"}))
        return 2
    try:
        out = asyncio.run(_run(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001
        out = {"error": f"{type(exc).__name__}: {exc}", "html": "", "status": 0}
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
