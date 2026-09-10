"""Ingestion orchestrator. Run from the CLI only — never from a request handler.

Flow per source:
  discover URLs (plain HTTP on the un-challenged sitemap)
    -> warm a single browser context (helps pass the JS challenge)
    -> render URLs in small concurrent batches (one retry batch for challenged pages)
    -> adapter.extract() -> Document + Passages + optional Property
    -> idempotent upsert (documents/passages superseded on hash change; properties
       replaced by stable id)
    -> append every record to a versioned JSONL snapshot
    -> write one crawl_runs entry with a coverage summary

A failed run never deletes previously good data.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import get_settings
from app.db import repo
from app.models.document import CrawlRun, FailedPage, SkippedPage
from app.models.property import Source
from app.scrapers import darglobal, wasalt
from app.scrapers.base import FetchSession
from app.scrapers.browser import BrowserFetcher, RenderedPage
from app.scrapers.model import ExtractedPage
from app.services.logging import get_logger

log = get_logger("estatelens.ingest")

_ADAPTERS = {Source.DARGLOBAL: darglobal, Source.WASALT: wasalt}
_WARM_URL = {
    Source.DARGLOBAL: "https://darglobal.co.uk/",
    Source.WASALT: "https://wasalt.sa/en",
}

SNAPSHOT_DIR = Path(__file__).resolve().parents[3] / "data" / "snapshots"


async def discover_urls(source: Source, limit: int) -> list[str]:
    adapter = _ADAPTERS[source]
    ua = get_settings().scraper_user_agent
    async with httpx.AsyncClient(headers={"User-Agent": ua}, follow_redirects=True) as client:
        return await adapter.discover(client, limit=limit)


async def run_crawl(
    source: Source,
    *,
    limit: int = 60,
    urls: list[str] | None = None,
    write_snapshot: bool = True,
    persist: bool = True,
    max_render_seconds: float = 600.0,
) -> CrawlRun:
    settings = get_settings()
    adapter = _ADAPTERS[source]
    run = CrawlRun(
        id=f"{source.value}-{uuid.uuid4().hex[:10]}",
        source=source,
        started_at=datetime.now(timezone.utc),
    )

    targets = urls or await discover_urls(source, limit)
    run.attempted_urls = list(targets)
    log.info("crawl start", extra={"source": source.value, "targets": len(targets)})

    robots = FetchSession()
    allowed: list[str] = []
    try:
        for url in targets:
            try:
                ok = await robots.allowed_by_robots(url)
            except Exception:  # noqa: BLE001
                ok = True
            if ok:
                allowed.append(url)
            else:
                run.skipped.append(SkippedPage(url=url, reason="disallowed by robots.txt"))
    finally:
        await robots.aclose()

    extracted: list[ExtractedPage] = []
    persist_lock = asyncio.Lock()

    # Snapshot is opened up front and appended per page (flushed), so a crash or
    # kill mid-run still leaves a usable, replayable artifact.
    snapshot_path = None
    snap = None
    if write_snapshot:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = run.started_at.strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = SNAPSHOT_DIR / f"{source.value}-{stamp}.jsonl"
        snap = snapshot_path.open("w", encoding="utf-8")

    async def _persist_and_record(page_result: ExtractedPage) -> None:
        async with persist_lock:
            extracted.append(page_result)
            if snap:
                _write_snapshot(snap, page_result)
            if persist:
                stored_doc, changed = await repo.upsert_document(page_result.document)
                if changed:
                    for p in page_result.passages:
                        p.document_id = stored_doc.id
                    await repo.replace_passages_for_document(stored_doc.id, page_result.passages)
                for pr in page_result.properties:
                    await repo.upsert_property(pr)

    # --- Wasalt property detail pages: use the site's own public JSON API ----
    if source is Source.WASALT:
        api_targets = [u for u in allowed if wasalt.is_pdp(u)]
        allowed = [u for u in allowed if not wasalt.is_pdp(u)]
        if api_targets:
            headers = {"User-Agent": settings.scraper_user_agent}
            sem = asyncio.Semaphore(max(2, settings.scraper_max_concurrency * 4))
            delay = max(0.05, settings.scraper_delay_seconds / 4)

            async def _one_pdp(client: httpx.AsyncClient, url: str) -> None:
                pid = wasalt.property_id_from_url(url)
                if not pid:
                    async with persist_lock:
                        run.skipped.append(SkippedPage(url=url, reason="no property id in url"))
                    return
                async with sem:
                    try:
                        data = await wasalt.fetch_api(client, pid)
                    except Exception as exc:  # noqa: BLE001
                        async with persist_lock:
                            run.failed.append(FailedPage(url=url, error=f"api: {exc}"[:300]))
                        return
                    if not data:
                        async with persist_lock:
                            run.skipped.append(
                                SkippedPage(url=url, reason="listing expired / not available from API")
                            )
                        return
                    try:
                        page_result = wasalt.build_from_api(url, data)
                        await wasalt.attach_listing_image(client, page_result)
                        await _persist_and_record(page_result)
                    except Exception as exc:  # noqa: BLE001
                        async with persist_lock:
                            run.failed.append(FailedPage(url=url, error=f"build/persist: {exc}"[:300]))
                        return
                    async with persist_lock:
                        run.succeeded.append(url)
                    await asyncio.sleep(delay)

            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
                # Chunk so progress is logged and memory stays bounded.
                chunk = 200
                for i in range(0, len(api_targets), chunk):
                    batch = api_targets[i : i + chunk]
                    log.info(
                        "wasalt api batch",
                        extra={
                            "batch": i // chunk + 1,
                            "size": len(batch),
                            "done": len(run.succeeded),
                            "total_pdps": len(api_targets),
                        },
                    )
                    # return_exceptions: one bad page must not cancel the batch
                    results = await asyncio.gather(
                        *(_one_pdp(client, u) for u in batch),
                        return_exceptions=True,
                    )
                    for url, res in zip(batch, results, strict=False):
                        if isinstance(res, Exception):
                            async with persist_lock:
                                run.failed.append(
                                    FailedPage(url=url, error=f"unhandled: {res}"[:300])
                                )

    if allowed:
        # Browser rendering (Incapsula-fronted pages) is the slow, fragile part.
        # Each page is rendered, extracted and persisted immediately, so a stuck
        # page never costs the pages already collected. The whole phase is also
        # bounded by wall-clock.
        async def _render_phase() -> None:
            async with BrowserFetcher(settle_seconds=6.0) as bf:
                try:
                    await bf.fetch(_WARM_URL[source])
                    await asyncio.sleep(2.0)
                except Exception as exc:  # noqa: BLE001
                    log.warning("warm-up failed", extra={"error": str(exc)[:200]})

                for url in allowed:
                    page = await bf.fetch(url)
                    if not (page.ok and not page.looks_like_challenge):
                        reason = page.error or "bot challenge"
                        (run.failed if "budget" not in reason and page.error else run.skipped).append(
                            FailedPage(url=url, error=reason[:300])
                            if "budget" not in reason and page.error
                            else SkippedPage(url=url, reason=reason)
                        )
                        continue
                    try:
                        result = adapter.extract(
                            url, page.final_url, page.html, page.status_code, page.title
                        )
                    except Exception as exc:  # noqa: BLE001
                        run.failed.append(FailedPage(url=url, error=f"extract: {exc}"[:300]))
                        continue
                    if len(result.document.cleaned_text) < 200:
                        run.skipped.append(SkippedPage(url=url, reason="near-empty after cleaning"))
                        continue
                    await _persist_and_record(result)
                    run.succeeded.append(url)
                    await asyncio.sleep(settings.scraper_delay_seconds)

        try:
            await asyncio.wait_for(_render_phase(), timeout=max_render_seconds)
        except asyncio.TimeoutError:
            done = set(run.succeeded) | {s.url for s in run.skipped} | {f.url for f in run.failed}
            for url in allowed:
                if url not in done:
                    run.skipped.append(
                        SkippedPage(url=url, reason="render phase wall-clock budget reached")
                    )
            log.warning("render phase timed out", extra={"collected": len(run.succeeded)})

    if snap:
        snap.close()

    run.finished_at = datetime.now(timezone.utc)
    run.coverage_summary = {
        "targets": len(targets),
        "succeeded": len(run.succeeded),
        "skipped": len(run.skipped),
        "failed": len(run.failed),
        "documents": len(extracted),
        "passages": sum(len(e.passages) for e in extracted),
        "properties": sum(len(e.properties) for e in extracted),
        "snapshot": str(snapshot_path) if snapshot_path else None,
    }
    if persist:
        await repo.save_crawl_run(run)
    log.info("crawl done", extra={"source": source.value, **run.coverage_summary})
    return run


def _snapshot_line(kind: str, model) -> str:
    return json.dumps(
        {"kind": kind, "data": json.loads(model.model_dump_json())}, ensure_ascii=False
    ) + "\n"


def _write_snapshot(fh, page: ExtractedPage) -> None:
    fh.write(_snapshot_line("document", page.document))
    for p in page.passages:
        fh.write(_snapshot_line("passage", p))
    for pr in page.properties:
        fh.write(_snapshot_line("property", pr))
    fh.flush()
