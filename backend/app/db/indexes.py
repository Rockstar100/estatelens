"""Index definitions, derived from the queries the app actually runs.

- ``properties`` is filtered by source + city + transaction + property type on
  Explore, and by id / source-record-id on upsert.
- ``passages`` is keyword-searched via a single text index and joined by property.
- ``documents`` is deduped by (source, canonical_url) and by content hash.
"""

from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel

from app.db.client import get_db

PROPERTY_INDEXES = [
    IndexModel([("id", ASCENDING)], name="uniq_id", unique=True),
    IndexModel(
        [("source", ASCENDING), ("source_record_id", ASCENDING)],
        name="uniq_source_record",
        unique=True,
        partialFilterExpression={"source_record_id": {"$type": "string"}},
    ),
    IndexModel(
        [
            ("source", ASCENDING),
            ("city", ASCENDING),
            ("transaction_type", ASCENDING),
            ("property_type", ASCENDING),
        ],
        name="explore_filter",
    ),
    IndexModel([("record_type", ASCENDING)], name="record_type"),
    IndexModel([("bedrooms", ASCENDING)], name="bedrooms"),
    IndexModel([("price_currency", ASCENDING), ("price_amount", ASCENDING)], name="price"),
]

DOCUMENT_INDEXES = [
    IndexModel([("id", ASCENDING)], name="uniq_id", unique=True),
    IndexModel(
        [("source", ASCENDING), ("canonical_url", ASCENDING)],
        name="uniq_source_url",
        unique=True,
    ),
    IndexModel([("content_hash", ASCENDING)], name="content_hash"),
]

PASSAGE_INDEXES = [
    IndexModel([("id", ASCENDING)], name="uniq_id", unique=True),
    IndexModel([("document_id", ASCENDING)], name="document_id"),
    IndexModel([("property_id", ASCENDING)], name="property_id"),
    IndexModel([("active", ASCENDING), ("source", ASCENDING)], name="active_source"),
    IndexModel(
        [("text", TEXT), ("page_title", TEXT), ("section_heading", TEXT)],
        name="passage_text",
        weights={"page_title": 8, "section_heading": 4, "text": 1},
        default_language="english",
    ),
]

CRAWL_RUN_INDEXES = [
    IndexModel([("id", ASCENDING)], name="uniq_id", unique=True),
    IndexModel([("source", ASCENDING), ("started_at", DESCENDING)], name="source_started"),
]

_ALL = {
    "properties": PROPERTY_INDEXES,
    "documents": DOCUMENT_INDEXES,
    "passages": PASSAGE_INDEXES,
    "crawl_runs": CRAWL_RUN_INDEXES,
}


async def ensure_indexes() -> dict[str, list[str]]:
    db = get_db()
    created: dict[str, list[str]] = {}
    for collection, models in _ALL.items():
        created[collection] = await db[collection].create_indexes(models)
    return created
