"""Build MongoDB property filters from a typed, allow-listed schema.

Nothing here ever executes a model-produced query. A caller supplies a
``PropertyFilter`` (validated Pydantic); this module turns it into a Mongo filter
document using only known fields and operators.

Numeric rules that keep unlike things apart:
  * An unknown price (``price_amount is None``) never satisfies a budget ceiling.
  * A budget filter only applies within a single currency.
  * Sale and rent are never mixed; rent bases (monthly/annual) are kept distinct.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from bson.decimal128 import Decimal128
from pydantic import BaseModel, Field, field_validator

from app.models.property import PriceBasis, RecordType, Source, TransactionType

_ALLOWED_SORTS = {
    "relevance": None,
    "price_asc": [("price_amount", 1)],
    "price_desc": [("price_amount", -1)],
    "newest": [("scraped_at", -1)],
}


class PropertyFilter(BaseModel):
    """The ONLY shape accepted for property filtering."""

    text: str | None = Field(default=None, max_length=200)
    source: Source | None = None
    record_type: RecordType | None = None
    country: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    transaction_type: TransactionType | None = None
    property_type: str | None = Field(default=None, max_length=80)
    bedrooms: int | None = Field(default=None, ge=0, le=50)
    bedrooms_min: int | None = Field(default=None, ge=0, le=50)
    budget_max: Decimal | None = Field(default=None, ge=0)
    budget_min: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    price_basis: PriceBasis | None = None
    sort: str = "relevance"

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v

    @field_validator("sort")
    @classmethod
    def _known_sort(cls, v: str) -> str:
        return v if v in _ALLOWED_SORTS else "relevance"

    @field_validator("budget_max", "budget_min", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: Any) -> Any:
        if v in (None, ""):
            return None
        try:
            return Decimal(str(v))
        except (InvalidOperation, ValueError):
            return None


def _ci_exact(value: str) -> dict:
    """Case-insensitive exact match, anchored (no regex injection: value is escaped)."""
    import re

    return {"$regex": f"^{re.escape(value.strip())}$", "$options": "i"}


def build_mongo_filter(f: PropertyFilter) -> tuple[dict[str, Any], list[tuple[str, int]] | None, list[str]]:
    """Return (mongo_filter, sort_spec, notes). ``notes`` explains constraints applied."""
    query: dict[str, Any] = {}
    notes: list[str] = []

    if f.source:
        query["source"] = f.source.value
    if f.record_type:
        query["record_type"] = f.record_type.value
    if f.transaction_type and f.transaction_type != TransactionType.UNSPECIFIED:
        query["transaction_type"] = f.transaction_type.value
        notes.append(f"transaction_type = {f.transaction_type.value}")
    if f.property_type:
        query["property_type"] = _ci_exact(f.property_type)
    for field in ("country", "city", "district"):
        val = getattr(f, field)
        if val:
            query[field] = _ci_exact(val)
            notes.append(f"{field} = {val}")

    if f.bedrooms is not None:
        query["bedrooms"] = f.bedrooms
        notes.append(f"bedrooms = {f.bedrooms}")
    elif f.bedrooms_min is not None:
        query["bedrooms"] = {"$gte": f.bedrooms_min}
        notes.append(f"bedrooms >= {f.bedrooms_min}")

    if f.price_basis:
        query["price_basis"] = f.price_basis.value

    budget = {}
    if f.budget_min is not None:
        budget["$gte"] = Decimal128(f.budget_min)
    if f.budget_max is not None:
        budget["$lte"] = Decimal128(f.budget_max)
    if budget:
        # Unknown prices must not qualify: require a non-null numeric price.
        query["price_amount"] = {**budget, "$ne": None}
        query["price_amount"]["$type"] = "decimal"
        if not f.currency:
            notes.append(
                "budget applied without a currency filter; results may mix currencies"
            )
        else:
            query["price_currency"] = f.currency
            notes.append(f"budget {f.budget_min or 0}-{f.budget_max or 'inf'} {f.currency}")

    if f.text:
        query["$text"] = {"$search": f.text}

    return query, _ALLOWED_SORTS.get(f.sort), notes
