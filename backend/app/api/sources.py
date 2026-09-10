"""Sources & About: real coverage numbers straight from the collections."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import get_settings
from app.db import repo
from app.models.api import SourceCoverage, SourcesResponse
from app.retrieval.pipeline import RETRIEVAL_METHOD

router = APIRouter(tags=["sources"])

_SITE = {"darglobal": "darglobal.co.uk", "wasalt": "wasalt.sa"}

# Recorded at implementation time — see docs/SUBMISSION.md. Kept here so the
# Sources page always states exactly which model was tested and when.
MODEL_TESTED_ON = "2026-09-10 (OpenRouter / Groq / Gemini OpenAI-compatible stream)"


@router.get("/sources", response_model=SourcesResponse)
async def sources() -> SourcesResponse:
    settings = get_settings()
    rows = await repo.coverage_by_source()
    counts = await repo.collection_counts()

    coverage = [
        SourceCoverage(
            source=r["source"],
            site=_SITE.get(r["source"], r["source"]),
            document_count=r["document_count"],
            property_count=r["property_count"],
            listing_count=r["listing_count"],
            development_count=r["development_count"],
            latest_collection=r["latest_collection"],
            cities=r["cities"],
            record_types=r["record_types"],
            extraction_failures=r["extraction_failures"],
        )
        for r in rows
    ]

    gaps: list[str] = []
    present = {r["source"] for r in rows}
    for expected in ("darglobal", "wasalt"):
        if expected not in present:
            gaps.append(f"No data collected yet from {expected}.")
    for r in rows:
        if r["property_count"] == 0:
            gaps.append(f"{r['source']}: pages collected but no structured property records parsed.")
        if not r["cities"]:
            gaps.append(f"{r['source']}: no city could be normalized for any record.")

    fallback_bits = []
    if settings.groq_api_key:
        fallback_bits.append(f"groq/{settings.groq_model}")
    if settings.gemini_api_key:
        fallback_bits.append(f"gemini/{settings.gemini_model}")
    if settings.openrouter_api_key:
        fallback_bits.append(settings.openrouter_fallback_model)

    return SourcesResponse(
        sources=coverage,
        total_documents=counts["documents"],
        total_properties=counts["properties"],
        total_passages=counts["passages"],
        retrieval_method=RETRIEVAL_METHOD,
        model=settings.active_llm_label,
        fallback_model=", ".join(fallback_bits) or settings.openrouter_fallback_model,
        model_tested_on=MODEL_TESTED_ON,
        coverage_gaps=gaps,
        generated_at=datetime.now(timezone.utc),
    )
