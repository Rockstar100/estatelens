"""Idempotent read/write operations over the four collections.

Every write is an upsert keyed by a stable identity, so re-running a crawl never
duplicates a record. When a document's content hash changes, its old passages are
marked ``active=False`` rather than deleted, and fresh passages are inserted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from app.db.client import get_db
from app.db.serde import (
    crawl_run_to_doc,
    doc_to_document,
    doc_to_passage,
    doc_to_property,
    document_to_doc,
    passage_to_doc,
    property_to_doc,
)
from app.models.document import CrawlRun, Document, Passage
from app.models.property import Property


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Documents & passages
# ---------------------------------------------------------------------------


async def upsert_document(document: Document) -> tuple[Document, bool]:
    """Upsert by (source, canonical_url). Returns (stored, content_changed).

    Does not re-read after write — on Atlas, a follow-up ``find_one`` can briefly
    return ``None`` under concurrent crawlers / replica lag and crash the run.
    """
    db = get_db()
    source = document.source.value if hasattr(document.source, "value") else document.source
    existing = await db.documents.find_one(
        {"source": source, "canonical_url": document.canonical_url}
    )
    changed = existing is None or existing.get("content_hash") != document.content_hash
    doc = document_to_doc(document)
    if existing:
        doc["_id"] = existing["_id"]
        doc["id"] = existing["_id"]
    await db.documents.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    stored_id = str(doc["_id"])
    if document.id == stored_id:
        return document, changed
    return document.model_copy(update={"id": stored_id}), changed


async def replace_passages_for_document(document_id: str, passages: list[Passage]) -> int:
    """Deactivate superseded passages, then insert the new set. Returns inserted count."""
    db = get_db()
    await db.passages.update_many(
        {"document_id": document_id, "active": True},
        {"$set": {"active": False, "superseded_at": _utcnow()}},
    )
    if not passages:
        return 0
    docs = [passage_to_doc(p) for p in passages]
    for d in docs:
        await db.passages.replace_one({"_id": d["_id"]}, d, upsert=True)
    return len(docs)


async def get_passages_by_ids(ids: list[str]) -> list[Passage]:
    if not ids:
        return []
    db = get_db()
    cursor = db.passages.find({"_id": {"$in": ids}})
    return [doc_to_passage(d) async for d in cursor]


async def search_passages(
    query: str,
    *,
    limit: int,
    sources: list[str] | None = None,
    property_ids: list[str] | None = None,
) -> list[tuple[Passage, float]]:
    """MongoDB text search (keyword, NOT semantic). Returns (passage, score) pairs."""
    db = get_db()
    match: dict[str, Any] = {"active": True, "$text": {"$search": query}}
    if sources:
        match["source"] = {"$in": sources}
    if property_ids:
        match["property_id"] = {"$in": property_ids}
    cursor = (
        db.passages.find(match, {"score": {"$meta": "textScore"}})
        .sort([("score", {"$meta": "textScore"})])
        .limit(limit)
    )
    out: list[tuple[Passage, float]] = []
    async for d in cursor:
        score = float(d.pop("score", 0.0))
        out.append((doc_to_passage(d), score))
    return out


async def sample_passages(limit: int, sources: list[str] | None = None) -> list[Passage]:
    db = get_db()
    match: dict[str, Any] = {"active": True}
    if sources:
        match["source"] = {"$in": sources}
    cursor = db.passages.find(match).limit(limit)
    return [doc_to_passage(d) async for d in cursor]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


async def upsert_property(prop: Property) -> None:
    db = get_db()
    await db.properties.replace_one({"_id": prop.id}, property_to_doc(prop), upsert=True)


async def get_property(property_id: str) -> Property | None:
    db = get_db()
    doc = await db.properties.find_one({"_id": property_id})
    return doc_to_property(doc) if doc else None


async def get_properties(ids: list[str]) -> list[Property]:
    if not ids:
        return []
    db = get_db()
    cursor = db.properties.find({"_id": {"$in": ids}})
    by_id = {d["_id"]: doc_to_property(d) async for d in cursor}
    return [by_id[i] for i in ids if i in by_id]


_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "and", "or", "to", "is", "are",
    "what", "which", "where", "when", "who", "how", "does", "do", "did", "say", "says",
    "tell", "me", "about", "show", "list", "give", "this", "that", "these", "those",
    "with", "by", "from", "its", "it", "collected", "source", "sources", "project",
    "projects", "property", "properties", "listing", "listings", "development",
    "developments", "compare", "handover", "price", "prices", "priced", "cost", "costs",
    "located", "location", "date", "only", "just", "also", "now", "then", "than",
    "least", "most", "more", "under", "over", "above", "below", "bedroom", "bedrooms",
    "bathroom", "bathrooms", "apartment", "apartments", "villa", "villas", "studio",
    "studios", "penthouse", "townhouse", "floor", "floors", "land", "sale", "rent",
    "rental", "rentals", "wasalt", "darglobal", "dar", "global", "cheapest", "expensive",
    "mention", "mentions", "waterfront", "golf", "course", "living", "unit", "units",
    "starting", "started", "start", "listed", "according", "data", "record", "records",
    "many", "much", "have", "has", "have", "been", "being", "vs", "versus", "between",
    "branded", "brand", "brands", "water", "near", "home", "homes", "house", "houses",
    "buyer", "buyers", "advising", "advise", "shortlist", "fit", "fits", "want", "wants",
    "sea", "beach", "ocean", "coastal", "seafront", "interiors",
    "amenities", "amenity", "designer", "designers", "connected", "kind", "product",
    "type", "types", "island", "marjan",
    # Too generic to pin a project alone
    "tower", "towers", "hotel", "hotels", "international", "residence", "residences",
    "next", "paper", "offerings", "offering", "same", "family", "differ", "similar",
    "different", "pages", "page", "support", "actually", "put", "side",
}


async def find_properties_by_title(text: str, *, limit: int = 3) -> list["Property"]:
    """Best-effort: match distinctive words from the question against property
    titles, so a question that names a project pulls that record. Case-insensitive
    substring on the longest non-stopword tokens; falls back to nothing."""
    import re as _re

    # Short / multi-word titles that stopwording would otherwise destroy.
    _PHRASE_TITLES = (
        "sea la vie", "da vinci", "elie saab", "trump tower", "urban oasis",
        "tierra viva", "amour sans", "les vagues", "the astera", "the mulliner",
    )

    tokens = []
    for t in _re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
        # Normalize possessives: "Neptune's" → "Neptune"
        if t.lower().endswith("'s") and len(t) > 4:
            t = t[:-2]
        elif t.lower().endswith("s'") and len(t) > 4:
            t = t[:-2]
        if t.lower() not in _STOPWORDS:
            tokens.append(t)
    tokens = sorted(set(tokens), key=len, reverse=True)[:6]
    db = get_db()
    scored: dict[str, tuple[Property, int]] = {}

    # Exact phrase boosts first (survives stopwording of "sea"/"la"/etc.).
    low = text.lower()
    for phrase in _PHRASE_TITLES:
        if phrase not in low:
            continue
        cursor = db.properties.find(
            {"title": {"$regex": _re.escape(phrase), "$options": "i"}}
        ).limit(2)
        async for d in cursor:
            p = doc_to_property(d)
            scored[p.id] = (p, max(scored.get(p.id, (p, 0))[1], 3))

    if not tokens and not scored:
        return []

    async def _search(toks: list[str], min_hits: int, cap: int) -> list[tuple[Property, int]]:
        if not toks:
            return []
        ors = [{"title": {"$regex": _re.escape(tok), "$options": "i"}} for tok in toks]
        pipeline = [
            {"$match": {"$or": ors}},
            {
                "$addFields": {
                    "_hits": {
                        "$size": {
                            "$filter": {
                                "input": [
                                    {
                                        "$regexMatch": {
                                            "input": {"$toLower": "$title"},
                                            "regex": _re.escape(tok.lower()),
                                        }
                                    }
                                    for tok in toks
                                ],
                                "cond": "$$this",
                            }
                        }
                    }
                }
            },
            {"$match": {"_hits": {"$gte": min_hits}}},
            {"$sort": {"_hits": -1}},
            {"$limit": cap},
        ]
        out: list[tuple[Property, int]] = []
        cursor = await db.properties.aggregate(pipeline)
        async for d in cursor:
            hits = int(d.pop("_hits", 0) or 0)
            out.append((doc_to_property(d), hits))
        return out

    # Multi-token hits first (Trump + Tower + Jeddah). Then add other strong
    # single names from the query that are not already covered (Neptune in a
    # compare), without pulling every loose "Trump …" sibling project.
    strong = [t for t in tokens if len(t) >= 5]
    multi_min = 2 if len(strong) >= 2 else 1
    if tokens:
        for prop, hits in await _search(tokens, min_hits=multi_min, cap=limit * 2):
            prev = scored.get(prop.id)
            scored[prop.id] = (prop, max(hits, prev[1] if prev else hits))
        covered = " ".join((p.title or "").lower() for p, h in scored.values() if h >= multi_min)
        want_all = bool(
            _re.search(r"\b(projects?|which|tied|related|all)\b", text, _re.I)
        )
        for tok in strong:
            if tok.lower() in covered and not want_all:
                continue
            for prop, hits in await _search(
                [tok], min_hits=1, cap=(limit if want_all else 1)
            ):
                prev = scored.get(prop.id)
                if prev is None or hits > prev[1]:
                    scored[prop.id] = (prop, max(hits, prev[1] if prev else hits))
                elif want_all and prop.id not in scored:
                    scored[prop.id] = (prop, hits)

    ranked = sorted(scored.values(), key=lambda x: (-x[1], x[0].title or ""))
    # One result per brand/family so "Trump Tower Jeddah" does not also keep
    # "Trump International Dubai" when both matched "Trump"/"Tower" — unless the
    # question compares two cities / same-family offerings.
    cities_in_q = _re.findall(
        r"\b(jeddah|dubai|doha|riyadh|muscat|london|benahav[ií]s|oman|spain|"
        r"ras\s+al\s+khaimah|marbella)\b",
        text,
        _re.I,
    )
    compare_same_brand = bool(
        _re.search(r"\b(compare|versus|vs\.?|next to|against|between)\b", text, _re.I)
        and len({c.lower() for c in cities_in_q}) >= 2
    )
    # "Which projects are tied to Missoni" should return every Missoni match.
    list_all_brand = bool(
        _re.search(r"\b(projects?|which|tied|related|all)\b", text, _re.I)
        and _re.search(
            r"\b(missoni|trump|pagani|mouawad|marriott|lamborghini|elie\s+saab)\b",
            text,
            _re.I,
        )
    )
    out: list[Property] = []
    seen_brand: set[str] = set()
    for prop, hits in ranked:
        title = (prop.title or "").lower()
        brand = next(
            (b for b in (
                "trump", "neptune", "astera", "missoni", "mulliner", "pagani",
                "lamborghini", "mouawad", "marriott", "wasalt", "elie saab",
                "marea", "sea la vie", "da vinci",
            ) if b in title),
            title.split("|")[0].strip()[:24],
        )
        # Soft single-token matches are weak; skip unless no better hits yet.
        if hits < 2 and out and not compare_same_brand and not list_all_brand:
            continue
        if brand in seen_brand and not compare_same_brand and not list_all_brand:
            continue
        if compare_same_brand and brand in seen_brand:
            # Allow a second same-brand hit only when its city is also in the query
            # and differs from the first.
            prev = next(p for p in out if brand in (p.title or "").lower())
            if (prop.city or "").lower() == (prev.city or "").lower():
                continue
            if prop.city and prop.city.lower() not in {c.lower() for c in cities_in_q}:
                continue
        if prop.id in {p.id for p in out}:
            continue
        seen_brand.add(brand)
        out.append(prop)
        if len(out) >= limit:
            break
    return out


_THEME_WATER = (
    "seafront", "waterfront", "beach", "beachfront", "sea-view", "sea view",
    "marina", "canal", "coastal", "cliff", "ocean", "harbour", "harbor",
)
_THEME_BRAND = (
    "branded", "interiors by", "trump", "missoni", "pagani", "aston martin",
    "lamborghini", "mouawad", "marriott", "elie saab", "w residences",
)


async def find_properties_by_theme(
    text: str,
    *,
    limit: int = 8,
    source: str | None = None,
) -> list["Property"]:
    """Match lifestyle themes (waterfront / branded) against title + description."""
    import re as _re

    low = text.lower()
    want_water = bool(_re.search(
        r"\b(water(?:front)?|sea(?:front)?|beach(?:front)?|ocean|marina|canal|"
        r"coast(?:al)?|cliff|harbour|harbor)\b",
        low,
    ))
    want_brand = bool(_re.search(
        r"\b(branded|brand|interiors?\s+by|trump|missoni|pagani|aston\s+martin|"
        r"lamborghini|mouawad|marriott|elie\s+saab)\b",
        low,
    ))
    if not want_water and not want_brand:
        return []

    terms: list[str] = []
    if want_water:
        terms.extend(_THEME_WATER)
    if want_brand and not want_water:
        # Brand-only questions: prefer explicit brand cues in titles.
        terms.extend(_THEME_BRAND)
    if want_water and want_brand:
        # Prefer water terms; brand is a soft preference in scoring below.
        terms.extend(_THEME_WATER)

    db = get_db()
    ors = []
    for term in terms:
        esc = _re.escape(term)
        ors.append({"title": {"$regex": esc, "$options": "i"}})
        ors.append({"description": {"$regex": esc, "$options": "i"}})
        ors.append({"amenities": {"$elemMatch": {"$regex": esc, "$options": "i"}}})
    q: dict[str, Any] = {"$or": ors}
    if source:
        q["source"] = source
    cursor = db.properties.find(q).limit(40)
    scored: list[tuple[int, Property]] = []
    async for d in cursor:
        p = doc_to_property(d)
        blob = " ".join(
            x for x in [
                p.title or "",
                p.description or "",
                " ".join(p.amenities or []),
            ]
        ).lower()
        score = 0
        if want_water:
            score += sum(
                2
                for t in _THEME_WATER
                if _re.search(rf"(?<![a-z]){_re.escape(t)}(?![a-z])", blob)
            )
        if want_brand:
            score += sum(
                1
                for t in _THEME_BRAND
                if _re.search(rf"(?<![a-z]){_re.escape(t)}(?![a-z])", blob)
            )
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1].title or ""))
    out: list[Property] = []
    seen: set[str] = set()
    for _sc, p in scored:
        if p.id in seen:
            continue
        seen.add(p.id)
        out.append(p)
        if len(out) >= limit:
            break
    return out


async def query_properties(
    mongo_filter: dict[str, Any],
    *,
    page: int,
    page_size: int,
    sort: list[tuple[str, int]] | None = None,
) -> tuple[list[Property], int]:
    db = get_db()
    total = await db.properties.count_documents(mongo_filter)
    skip = max(page - 1, 0) * page_size

    # MongoDB sorts NULL/missing before numbers; for a numeric sort the user
    # wants the records that HAVE that value ordered, and the ones missing it
    # last (either direction). A two-key sort (has-value, then value) does that
    # without an out-of-range numeric sentinel. Applies to price and area.
    num_field, num_dir = next(
        ((f, d) for f, d in (sort or []) if f in ("price_amount", "area_value")),
        (None, None),
    )
    if num_field is not None:
        pipeline = [
            {"$match": mongo_filter},
            {"$addFields": {"_hasval": {"$cond": [{"$eq": [f"${num_field}", None]}, 1, 0]}}},
            {"$sort": {"_hasval": 1, num_field: num_dir, "_id": 1}},
            {"$skip": skip},
            {"$limit": page_size},
            {"$project": {"_hasval": 0}},
        ]
        cursor = await db.properties.aggregate(pipeline)
        items = [doc_to_property(d) async for d in cursor]
        return items, total

    cursor = db.properties.find(mongo_filter)
    if sort:
        cursor = cursor.sort(sort)
    cursor = cursor.skip(skip).limit(page_size)
    items = [doc_to_property(d) async for d in cursor]
    return items, total


async def property_facets(base_filter: dict[str, Any] | None = None) -> dict[str, list[dict]]:
    """Distinct filter values + counts, built from the data itself."""
    db = get_db()
    base = base_filter or {}

    def _facet(field: str) -> list[dict]:
        return [
            {"$match": base},
            {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
            {"$match": {"_id": {"$ne": None}}},
            {"$sort": {"count": -1, "_id": 1}},
            {"$project": {"_id": 0, "value": {"$toString": "$_id"}, "count": 1}},
        ]

    pipeline = [
        {
            "$facet": {
                "sources": _facet("source"),
                "cities": _facet("city"),
                "property_types": _facet("property_type"),
                "record_types": _facet("record_type"),
                "transaction_types": _facet("transaction_type"),
                "bedrooms": _facet("bedrooms"),
                "currencies": _facet("price_currency"),
            }
        }
    ]
    cursor = await db.properties.aggregate(pipeline)
    result = await cursor.to_list(1)
    return result[0] if result else {}


# ---------------------------------------------------------------------------
# Crawl runs & coverage
# ---------------------------------------------------------------------------


async def save_crawl_run(run: CrawlRun) -> None:
    db = get_db()
    await db.crawl_runs.replace_one({"_id": run.id}, crawl_run_to_doc(run), upsert=True)


async def coverage_by_source() -> list[dict[str, Any]]:
    db = get_db()
    docs_pipeline = [
        {
            "$group": {
                "_id": "$source",
                "document_count": {"$sum": 1},
                "latest_collection": {"$max": "$fetched_at"},
                "failures": {
                    "$sum": {"$cond": [{"$eq": ["$extraction_status", "failed"]}, 1, 0]}
                },
            }
        }
    ]
    props_pipeline = [
        {
            "$group": {
                "_id": "$source",
                "property_count": {"$sum": 1},
                "listing_count": {
                    "$sum": {"$cond": [{"$eq": ["$record_type", "listing"]}, 1, 0]}
                },
                "development_count": {
                    "$sum": {"$cond": [{"$eq": ["$record_type", "development"]}, 1, 0]}
                },
                "cities": {"$addToSet": "$city"},
                "record_types": {"$addToSet": "$record_type"},
            }
        }
    ]
    docs = {d["_id"]: d async for d in await db.documents.aggregate(docs_pipeline)}
    props = {d["_id"]: d async for d in await db.properties.aggregate(props_pipeline)}
    sources = sorted(set(docs) | set(props))
    out = []
    for src in sources:
        d = docs.get(src, {})
        p = props.get(src, {})
        cities = sorted(c for c in p.get("cities", []) if c)
        out.append(
            {
                "source": src,
                "document_count": d.get("document_count", 0),
                "property_count": p.get("property_count", 0),
                "listing_count": p.get("listing_count", 0),
                "development_count": p.get("development_count", 0),
                "latest_collection": d.get("latest_collection"),
                "cities": cities,
                "record_types": sorted(rt for rt in p.get("record_types", []) if rt),
                "extraction_failures": d.get("failures", 0),
            }
        )
    return out


async def collection_counts() -> dict[str, int]:
    db = get_db()
    return {
        "properties": await db.properties.count_documents({}),
        "documents": await db.documents.count_documents({}),
        "passages": await db.passages.count_documents({"active": True}),
        "crawl_runs": await db.crawl_runs.count_documents({}),
    }
