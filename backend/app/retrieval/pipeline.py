"""Assemble grounded evidence for a chat turn.

Method (documented plainly for the Sources page):
  1. Deterministically extract a typed filter from the latest user message and
     merge it with any explicit filters carried in the conversation context.
  2. Resolve ordinal references ("the first and third") against the ids last shown.
  3. Structured MongoDB query for matching property records (exact numeric rules).
  4. MongoDB **text search** (keyword) over passages for descriptive questions and
     for passages tied to the selected/among-returned properties.
  5. **Optional semantic layer** — when passage vectors are indexed (``embed``
     CLI) and a query embedding is available, blend cosine similarity with the
     keyword score and pull in strong semantic matches the keyword search missed.
     Absent vectors / API → step 4 alone, unchanged.
  6. De-duplicate, cap at ``retrieval_passage_limit``, and number the evidence.
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
from app.retrieval.semantic import semantic_scores

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


async def _known_places() -> set[str]:
    """Lower-cased city / district / country values that appear in the data."""
    db = repo.get_db()
    out: set[str] = set()
    for field in ("city", "district", "country"):
        for v in await db.properties.distinct(field):
            if isinstance(v, str) and v.strip():
                out.add(v.strip().lower())
    return out


# "... in Cairo", "near Tokyo", "properties at Marbella" — capture the place.
_PLACE_IN_TEXT = re.compile(
    r"\b(?:in|at|near|around|within|located in|based in)\s+"
    r"([A-Z][A-Za-z]+(?:[ -][A-Z][A-Za-z]+){0,2})"
)
# Words that follow "in/at" but are not places.
_NOT_A_PLACE = {
    "the", "this", "that", "riyal", "saudi", "sar", "aed", "usd", "each",
    "total", "cash", "stock", "general", "december", "january",
}


def _unknown_location(user_text: str, known: set[str]) -> str | None:
    """Return a place named in the query that does not appear anywhere in the
    collected data (so a location-scoped search should abstain, not fall back to
    unrelated records). Returns None if any named place is known, or if no place
    is named at all."""
    candidates: list[str] = []
    for m in _PLACE_IN_TEXT.finditer(user_text):
        place = m.group(1).strip()
        low = place.lower()
        if low in _NOT_A_PLACE or low.split()[0] in _NOT_A_PLACE:
            continue
        if any(low == k or low in k or k in low for k in known):
            return None  # a real place is named — let the search run
        candidates.append(place)
    return candidates[0] if candidates else None


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
    # listings); a real structured query names a place, size, price or type,
    # OR asks for a ranking ("cheapest", "sort by price").
    _weak = {"source", "text", "sort"}
    strong_structured = any(
        v not in (None, "", "relevance")
        for k, v in merged.model_dump().items()
        if k not in _weak
    )
    ranked = merged.sort != "relevance"
    wants_listings = strong_structured or ranked

    # A query scoped to a place we have nothing for ("apartments in Cairo") must
    # abstain, not fall back to showing unrelated records from other cities.
    bad_place = None
    if not (merged.city or merged.district or merged.country):
        bad_place = _unknown_location(user_text, await _known_places())
    if bad_place:
        wants_listings = False
        result.filter_notes = [f"no collected records in {bad_place}"]
        result.applied_filters = {}
        result.properties = []
        result.evidence = []
        return result

    mongo_filter, sort_spec, notes = build_mongo_filter(merged)
    result.filter_notes = notes

    properties: list[Property] = []
    if selected_ids:
        properties = await repo.get_properties(selected_ids)

    # Name matching is for "Trump Tower Jeddah"-style questions. Always try it —
    # even alongside structured filters — so a named project is not dropped when
    # the user also says "for sale" / "bedrooms" / etc. Prefer named hits first.
    named = await repo.find_properties_by_title(user_text, limit=3)
    named_ids = {p.id for p in named}
    for p in named:
        if p.id not in {x.id for x in properties}:
            properties.append(p)

    ranked_hits: list[Property] = []
    if wants_listings or selected_ids or merged.text:
        page_items, _total = await repo.query_properties(
            mongo_filter, page=1, page_size=12, sort=sort_spec
        )
        ranked_hits = page_items
        for p in page_items:
            if p.id not in {x.id for x in properties}:
                properties.append(p)

    # Named matches first so the model sees the asked-about record before a
    # broad filter dump (unless a ranked query needs price/area order).
    if named and not ranked:
        named_first = [p for p in named]
        rest = [p for p in properties if p.id not in named_ids]
        properties = named_first + rest

    # For a ranked query ("cheapest …") the ordering carries the answer — put the
    # ranked results first so the model reads them in order, and always keep the
    # true #1 even if a title match jumped the queue.
    if ranked and ranked_hits:
        top = ranked_hits[0]
        rest = [p for p in properties if p.id != top.id]
        properties = [top] + rest

    if selected_ids or named_ids or wants_listings or 0 < len(properties) <= 6:
        result.properties = properties[:6]
    else:
        result.properties = []

    # --- passage keyword search --------------------------------------
    search_terms = merged.text or user_text
    sources = [merged.source.value] if merged.source else None
    scored = await repo.search_passages(search_terms, limit=limit * 3, sources=sources)

    # Passages tied to the specific properties the user selected, a *strong*
    # structured query surfaced, or a *ranked* query put on top take priority —
    # a bare "what does X say" question keeps the free-text ranking.
    prop_ids = [p.id for p in result.properties]
    if prop_ids and (selected_ids or strong_structured or ranked):
        tied = await repo.search_passages(
            search_terms or "amenities location price",
            limit=limit,
            property_ids=prop_ids,
        )
        # For a ranked query, order the tied passages to match the card order.
        if ranked:
            rank = {pid: i for i, pid in enumerate(prop_ids)}
            tied.sort(key=lambda s: rank.get(s[0].property_id, 999))
        scored = tied + [s for s in scored if s[0].id not in {t[0].id for t in tied}]

    # --- semantic re-rank + recall (optional hybrid layer) -------------
    # Blend cosine similarity from passage embeddings with the lexical score, and
    # pull in strong semantic matches the keyword search missed. Skipped for a
    # ranked query (there the card order carries the answer) and when no vectors
    # are indexed / the query can't be embedded.
    if not ranked:
        allowed_pids = {p.id for p in result.properties} or None
        sem = await semantic_scores(
            search_terms, allowed_property_ids=allowed_pids, top_k=limit * 3
        )
        if sem:
            lex = {p.id: sc for p, sc in scored}
            lex_max = max(lex.values(), default=0.0) or 1.0
            missing = [pid for pid in sem if pid not in lex]
            if missing:
                extra = await repo.get_passages_by_ids(missing)
                if sources:
                    extra = [
                        p for p in extra
                        if getattr(p.source, "value", p.source) in sources
                    ]
                scored = scored + [(p, 0.0) for p in extra]
            w = settings.embedding_weight

            def _blend(item: tuple) -> float:
                p, sc = item
                lex_n = (sc / lex_max) if lex_max else 0.0
                return w * sem.get(p.id, 0.0) + (1.0 - w) * lex_n

            scored = sorted(scored, key=_blend, reverse=True)

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
