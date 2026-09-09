"""Conversion between Pydantic models and BSON documents.

Money and area are stored as ``Decimal128`` so arithmetic and range queries stay
exact. ``None`` is preserved (never turned into ``0``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from bson.decimal128 import Decimal128

from app.models.document import CrawlRun, Document, Passage
from app.models.property import Property

_DECIMAL_FIELDS = ("price_amount", "area_value")


def property_to_doc(prop: Property) -> dict[str, Any]:
    doc = prop.model_dump(mode="python")
    for field in _DECIMAL_FIELDS:
        value = doc.get(field)
        doc[field] = None if value is None else Decimal128(Decimal(str(value)))
    doc["_id"] = doc["id"]
    return doc


def doc_to_property(doc: dict[str, Any]) -> Property:
    data = dict(doc)
    data.pop("_id", None)
    for field in _DECIMAL_FIELDS:
        value = data.get(field)
        if isinstance(value, Decimal128):
            data[field] = value.to_decimal()
    return Property.model_validate(data)


def document_to_doc(document: Document) -> dict[str, Any]:
    doc = document.model_dump(mode="python")
    doc["_id"] = doc["id"]
    return doc


def doc_to_document(doc: dict[str, Any]) -> Document:
    data = dict(doc)
    data.pop("_id", None)
    return Document.model_validate(data)


def passage_to_doc(passage: Passage) -> dict[str, Any]:
    doc = passage.model_dump(mode="python")
    doc["_id"] = doc["id"]
    return doc


def doc_to_passage(doc: dict[str, Any]) -> Passage:
    data = dict(doc)
    data.pop("_id", None)
    return Passage.model_validate(data)


def crawl_run_to_doc(run: CrawlRun) -> dict[str, Any]:
    doc = run.model_dump(mode="python")
    doc["_id"] = doc["id"]
    return doc
