"""Sources & About: real coverage numbers straight from the collections."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import get_settings
from app.db import repo
from app.models.api import SourceCoverage, SourcesResponse
from app.retrieval.pipeline import retrieval_method_description

router = APIRouter(tags=["sources"])

_SITE = {"darglobal": "darglobal.co.uk", "wasalt": "wasalt.sa"}

# Display fixes for cities corrupted by historical encoding glitches in Mongo.
_CITY_ALIASES = {
    "benahavis": "Benahavís",
    "benahavís": "Benahavís",
    "benahavã­s": "Benahavís",
    "benahavÃ­s": "Benahavís",
    "benahava-s": "Benahavís",
}


def _display_city(raw: str) -> str:
    key = raw.strip()
    low = key.lower()
    if low in _CITY_ALIASES:
        return _CITY_ALIASES[low]
    # Fold accent / mojibake residue so "BenahavA-s" still maps.
    folded = (
        low.replace("í", "i")
        .replace("ã­", "i")
        .replace("Ã­", "i")
        .replace("a-s", "is")
        .replace(" ", "")
    )
    if folded.startswith("benahav") and folded.endswith("is"):
        return "Benahavís"
    return key


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
            cities=sorted({_display_city(c) for c in r["cities"] if c}),
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

    primary = settings.active_llm_label
    pref = (settings.llm_provider or "auto").strip().lower()
    chain: list[str] = []
    if pref in {"groq", "gemini", "openrouter"}:
        # Pinned provider — only show that provider's model ladder.
        if pref == "groq" and settings.groq_api_key:
            chain.append(f"groq/{settings.groq_model}")
        elif pref == "gemini" and settings.gemini_api_key:
            chain.append(f"gemini/{settings.gemini_model}")
        elif pref == "openrouter" and settings.openrouter_api_key:
            chain.append(f"openrouter/{settings.openrouter_model}")
            if (
                settings.openrouter_fallback_model
                and settings.openrouter_fallback_model != settings.openrouter_model
            ):
                chain.append(f"openrouter/{settings.openrouter_fallback_model}")
    else:
        # auto: Groq → Gemini → OpenRouter (matches LLMClient._providers).
        if settings.groq_api_key:
            chain.append(f"groq/{settings.groq_model}")
        if settings.gemini_api_key:
            chain.append(f"gemini/{settings.gemini_model}")
        if settings.openrouter_api_key:
            chain.append(f"openrouter/{settings.openrouter_model}")
            if (
                settings.openrouter_fallback_model
                and settings.openrouter_fallback_model != settings.openrouter_model
            ):
                chain.append(f"openrouter/{settings.openrouter_fallback_model}")
    # Fallbacks = everyone in the real chain after the primary (exclude dupes).
    # Normalize primary label so "nvidia/…" matches "openrouter/nvidia/…".
    primary_aliases = {primary, primary.removeprefix("openrouter/")}
    if primary.startswith("openrouter/"):
        primary_aliases.add(primary.split("/", 1)[-1])
    seen: set[str] = set(primary_aliases)
    fallback_bits: list[str] = []
    for label in chain:
        bare = label.removeprefix("openrouter/")
        if label in seen or bare in seen:
            continue
        seen.add(label)
        seen.add(bare)
        fallback_bits.append(label)

    return SourcesResponse(
        sources=coverage,
        total_documents=counts["documents"],
        total_properties=counts["properties"],
        total_passages=counts["passages"],
        retrieval_method=retrieval_method_description(),
        model=primary,
        fallback_model=" → ".join(fallback_bits) if fallback_bits else "(none configured)",
        model_tested_on=MODEL_TESTED_ON,
        coverage_gaps=gaps,
        generated_at=datetime.now(timezone.utc),
    )
