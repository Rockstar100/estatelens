"""Assemble grounded evidence for a chat turn.

Method (documented plainly for the Sources page):
  1. Deterministically extract a typed filter from the latest user message and
     merge it with any explicit filters carried in the conversation context.
  2. Resolve ordinal references ("the first and third") against the ids last shown.
  3. Structured MongoDB query for matching property records (exact numeric rules).
  4. MongoDB **text search** (keyword, not semantic) over passages for descriptive
     questions and for passages tied to the selected/among-returned properties.
  5. De-duplicate, cap at ``retrieval_passage_limit``, and number the evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.config import get_settings
from app.db import repo
from app.models.api import EvidenceItem
from app.models.property import Property
from app.retrieval.filters import PropertyFilter, build_mongo_filter
from app.retrieval.nlu import extract_filter, merge_filters, resolve_ordinal_reference

RETRIEVAL_METHOD = (
    "Structured MongoDB filtering over normalized property records plus MongoDB "
    "text-index keyword search over source passages. This is lexical retrieval, "
    "not vector/semantic search."
)

_SITE = {"darglobal": "DarGlobal", "wasalt": "Wasalt"}


@dataclass
class RetrievalResult:
    evidence: list[EvidenceItem] = field(default_factory=list)
    properties: list[Property] = field(default_factory=list)
    applied_filters: dict = field(default_factory=dict)
    filter_notes: list[str] = field(default_factory=list)
    selected_property_ids: list[str] = field(default_factory=list)
    ambiguous: str | None = None

    def evidence_ids(self) -> list[str]:
        return [e.id for e in self.evidence]


_TAG_RE = re.compile(r"<[^>]+>")


def _excerpt(text: str, limit: int = 320) -> str:
    # Defence in depth: strip any stray HTML tags from source text before it
    # goes out in an `evidence` event (the client also sanitises, and renders
    # excerpts as plain text, but keep the wire clean).
    text = " ".join(_TAG_RE.sub("", text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def _known_cities() -> list[str]:
    facets = await repo.property_facets()
    return [f["value"] for f in facets.get("cities", [])]


# Only these keys are honoured from a client-supplied context filter.
_CONTEXT_FILTER_KEYS = {
    "text", "source", "record_type", "country", "city", "district",
    "transaction_type", "property_type", "bedrooms", "bedrooms_min",
    "budget_max", "budget_min", "currency", "price_basis", "sort",
}


def _safe_context_filter(raw: object) -> PropertyFilter:
    """Never raises: pick only allow-listed keys with scalar values, then try to
    validate; on any failure, drop offending keys one at a time; worst case,
    return an empty filter."""
    if not isinstance(raw, dict):
        return PropertyFilter()
    clean = {
        k: v
        for k, v in raw.items()
        if k in _CONTEXT_FILTER_KEYS and isinstance(v, (str, int, float, bool)) and not isinstance(v, bool)
    }
    while True:
        try:
            return PropertyFilter.model_validate(clean)
        except ValidationError as exc:
            bad = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")}
            if not bad or not (clean.keys() & bad):
                return PropertyFilter()
            for k in bad:
                clean.pop(k, None)


async def retrieve(
    user_text: str,
    *,
    context_filters: dict | None = None,
    selected_property_ids: list[str] | None = None,
    last_result_ids: list[str] | None = None,
) -> RetrievalResult:
    settings = get_settings()
    limit = settings.retrieval_passage_limit

    # Client-supplied context is advisory: a malformed `filters` object must not
    # break the turn — only keys that validate against the allow-listed schema
    # are kept, everything else is dropped.
    base_filter = _safe_context_filter(context_filters)
    turn_filter = extract_filter(user_text, known_cities=await _known_cities())
    merged = merge_filters(base_filter, turn_filter)

    # --- ordinal / explicit property selection --------------------------
    selected_ids = [
        s for s in (str(x).strip() for x in (selected_property_ids or []))
        if s and len(s) <= 200
    ][:3]
    ordinal_ids = resolve_ordinal_reference(user_text, last_result_ids or [])
    for i in ordinal_ids:
        if i not in selected_ids:
            selected_ids.append(i)

    result = RetrievalResult(
        applied_filters=merged.model_dump(exclude_none=True, exclude_defaults=True),
        selected_property_ids=selected_ids,
    )

    # --- structured property query -------------------------------------
    # `source` alone is a weak signal (it does not mean the user wants a list of
    # listings); a real structured query names a place, size, price or type.
    _weak = {"source", "text", "sort"}
    strong_structured = any(
        v not in (None, "", "relevance")
        for k, v in merged.model_dump().items()
        if k not in _weak
    )
    has_structured = strong_structured or merged.source is not None
    mongo_filter, sort_spec, notes = build_mongo_filter(merged)
    result.filter_notes = notes

    properties: list[Property] = []
    if selected_ids:
        properties = await repo.get_properties(selected_ids)

    # A question that names a project/listing should always pull that record so
    # its structured facts (price, handover, area…) reach the model.
    named = await repo.find_properties_by_title(user_text, limit=3)
    named_ids = {p.id for p in named}
    for p in named:
        if p.id not in {x.id for x in properties}:
            properties.append(p)

    if strong_structured or selected_ids or (merged.text and not selected_ids):
        page_items, _total = await repo.query_properties(
            mongo_filter, page=1, page_size=12, sort=sort_spec
        )
        for p in page_items:
            if p.id not in {x.id for x in properties}:
                properties.append(p)

    # Surface cards only when the user narrowed things down or the set is small
    # enough to be useful — not a full dump for a "what does X say" question.
    if selected_ids or named_ids or strong_structured or 0 < len(properties) <= 6:
        result.properties = properties[:6]
    else:
        result.properties = []

    # --- passage keyword search --------------------------------------
    search_terms = merged.text or user_text
    sources = [merged.source.value] if merged.source else None
    scored = await repo.search_passages(search_terms, limit=limit * 3, sources=sources)

    # Passages tied to the specific properties the user selected or that a *strong*
    # structured query surfaced take priority — but a bare "what does X say"
    # question keeps the free-text ranking.
    prop_ids = [p.id for p in result.properties]
    if prop_ids and (selected_ids or strong_structured):
        tied = await repo.search_passages(
            search_terms or "amenities location price",
            limit=limit,
            property_ids=prop_ids,
        )
        scored = tied + [s for s in scored if s[0].id not in {t[0].id for t in tied}]

    if not scored and not result.properties:
        # last resort: give the model *something* real to describe coverage from
        fallback = await repo.sample_passages(limit, sources=sources)
        scored = [(p, 0.0) for p in fallback]

    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    per_doc: dict[str, int] = {}
    ordinal = 0
    for passage, _score in scored:
        if passage.id in seen_ids or passage.content_hash in seen_hashes:
            continue  # exact-duplicate passage text (e.g. a site-wide FAQ block)
        if per_doc.get(passage.document_id, 0) >= 2:
            continue  # at most two passages from any one page
        seen_ids.add(passage.id)
        seen_hashes.add(passage.content_hash)
        per_doc[passage.document_id] = per_doc.get(passage.document_id, 0) + 1
        ordinal += 1
        src = getattr(passage.source, "value", passage.source)
        result.evidence.append(
            EvidenceItem(
                id=passage.id,
                ordinal=ordinal,
                source=src,
                site=_SITE.get(src, str(src).title()),
                title=passage.page_title,
                section_heading=passage.section_heading,
                excerpt=_excerpt(passage.text),
                url=passage.canonical_url,
                collected_at=passage.collected_at,
            )
        )
        if ordinal >= limit:
            break

    return result
