"""EstateLens ingestion & maintenance CLI.

    python -m scripts.cli scrape --source all --limit 60
    python -m scripts.cli validate
    python -m scripts.cli create-indexes
    python -m scripts.cli coverage
    python -m scripts.cli export-snapshot --out data/snapshots/full-YYYYMMDD.jsonl
    python -m scripts.cli import-snapshot data/snapshots/full-YYYYMMDD.jsonl

Never invoked by the web app; ingestion is CLI-only.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.config import get_settings
from app.db import client as db_client
from app.db import repo
from app.db.indexes import ensure_indexes
from app.db.serde import doc_to_document, doc_to_passage, doc_to_property
from app.models.document import Document, Passage
from app.models.property import Property, Source
from app.scrapers.pipeline import SNAPSHOT_DIR, run_crawl
from app.services.logging import configure_logging

app = typer.Typer(add_completion=False, help="EstateLens ingestion & maintenance CLI")
console = Console()


def _run(coro):
    configure_logging(get_settings().log_level)

    async def _wrapper():
        await db_client.connect()
        try:
            return await coro
        finally:
            await db_client.disconnect()

    return asyncio.run(_wrapper())


@app.command()
def scrape(
    source: str = typer.Option("all", help="darglobal | wasalt | all"),
    limit: int = typer.Option(60, help="max pages per source"),
    persist: bool = typer.Option(True, help="write to MongoDB"),
    snapshot: bool = typer.Option(True, help="write a JSONL snapshot"),
    max_render_seconds: float = typer.Option(
        600.0, help="wall-clock ceiling for the browser-render phase per source"
    ),
) -> None:
    """Crawl public pages, normalize, and (idempotently) store them."""
    sources = [Source.DARGLOBAL, Source.WASALT] if source == "all" else [Source(source)]

    async def _go():
        for src in sources:
            console.rule(f"[bold]{src.value}")
            run = await run_crawl(
                src,
                limit=limit,
                write_snapshot=snapshot,
                persist=persist,
                max_render_seconds=max_render_seconds,
            )
            console.print_json(json.dumps(run.coverage_summary))
            if run.failed:
                console.print(f"[yellow]{len(run.failed)} failed:[/] "
                              + ", ".join(f.url for f in run.failed[:8]))
            if run.skipped:
                console.print(f"[dim]{len(run.skipped)} skipped[/]")

    _run(_go())


@app.command()
def validate() -> None:
    """Check stored records for integrity problems (null-vs-zero, identity, orphans)."""

    async def _go():
        db = db_client.get_db()
        problems: list[str] = []

        async for d in db.properties.find({}):
            try:
                prop = doc_to_property(d)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"property {d.get('_id')}: invalid ({exc})")
                continue
            for money_field in ("price_amount", "area_value"):
                if d.get(money_field) == 0:
                    problems.append(f"{prop.id}: {money_field} stored as 0 (should be null)")
            if prop.bedrooms == 0 and prop.property_type not in ("studio", None):
                problems.append(f"{prop.id}: bedrooms=0 but type={prop.property_type}")
            if not prop.source_url.startswith("http"):
                problems.append(f"{prop.id}: source_url not absolute")
            if prop.price_amount is not None and prop.price_currency is None:
                problems.append(f"{prop.id}: price without currency")
            for ev in prop.evidence:
                if not await db.passages.find_one({"_id": ev.passage_id}):
                    problems.append(f"{prop.id}: evidence passage {ev.passage_id} missing")

        dangling = 0
        async for p in db.passages.find({"active": True, "property_id": {"$ne": None}}):
            if not await db.properties.find_one({"_id": p["property_id"]}):
                dangling += 1
        if dangling:
            problems.append(f"{dangling} active passages reference a missing property")

        counts = await repo.collection_counts()
        console.print(counts)
        if problems:
            console.print(f"[red]{len(problems)} problem(s):")
            for p in problems[:50]:
                console.print(f"  - {p}")
            raise typer.Exit(1)
        console.print("[green]validation passed")

    _run(_go())


@app.command("create-indexes")
def create_indexes() -> None:
    """Create every index the app queries against."""

    async def _go():
        created = await ensure_indexes()
        for coll, names in created.items():
            console.print(f"[cyan]{coll}[/]: {', '.join(names)}")

    _run(_go())


@app.command()
def coverage() -> None:
    """Print collection counts and per-source coverage."""

    async def _go():
        counts = await repo.collection_counts()
        rows = await repo.coverage_by_source()
        console.print(counts)
        table = Table("source", "docs", "properties", "listings", "devs", "latest", "cities")
        for r in rows:
            table.add_row(
                r["source"],
                str(r["document_count"]),
                str(r["property_count"]),
                str(r["listing_count"]),
                str(r["development_count"]),
                str(r["latest_collection"]),
                ", ".join(r["cities"][:6]),
            )
        console.print(table)

    _run(_go())


@app.command("export-snapshot")
def export_snapshot(out: Path = typer.Option(None, help="output .jsonl path")) -> None:
    """Dump the whole store to a single JSONL snapshot (recovery / reproducibility)."""

    async def _go():
        db = db_client.get_db()
        target = out or SNAPSHOT_DIR / "full-export.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with target.open("w", encoding="utf-8") as fh:
            for kind, coll, conv in (
                ("document", db.documents, doc_to_document),
                ("passage", db.passages, doc_to_passage),
                ("property", db.properties, doc_to_property),
            ):
                async for d in coll.find({}):
                    fh.write(
                        json.dumps(
                            {"kind": kind, "data": json.loads(conv(d).model_dump_json())},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    n += 1
        console.print(f"[green]wrote {n} records -> {target}")

    _run(_go())


@app.command("import-snapshot")
def import_snapshot(path: Path = typer.Argument(..., help=".jsonl snapshot to load")) -> None:
    """Load a JSONL snapshot into MongoDB (idempotent upserts)."""

    async def _go():
        if not path.exists():
            console.print(f"[red]no such file: {path}")
            raise typer.Exit(1)
        counts = {"document": 0, "passage": 0, "property": 0}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            kind, data = rec["kind"], rec["data"]
            if kind == "document":
                doc, _ = await repo.upsert_document(Document.model_validate(data))
            elif kind == "passage":
                p = Passage.model_validate(data)
                await db_client.get_db().passages.replace_one(
                    {"_id": p.id}, {**p.model_dump(mode="python"), "_id": p.id}, upsert=True
                )
            elif kind == "property":
                await repo.upsert_property(Property.model_validate(data))
            else:
                continue
            counts[kind] = counts.get(kind, 0) + 1
        console.print(f"[green]imported {counts}")

    _run(_go())


if __name__ == "__main__":
    app()
