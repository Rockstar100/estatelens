"""Normalized property / development records.

A ``Property`` is either an individual listing (a specific unit for sale or rent)
or a development (a project marketed as a whole). Unknown values are ``None`` and
are never coerced to zero. Money is carried as an exact ``Decimal`` and serialized
as a string by the API so no precision is lost in transit.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Source(str, Enum):
    DARGLOBAL = "darglobal"
    WASALT = "wasalt"


class RecordType(str, Enum):
    LISTING = "listing"
    DEVELOPMENT = "development"


class TransactionType(str, Enum):
    SALE = "sale"
    RENT = "rent"
    UNSPECIFIED = "unspecified"


class PriceBasis(str, Enum):
    """How a price figure should be read. Prevents comparing unlike numbers."""

    TOTAL = "total"
    STARTING = "starting"
    MONTHLY_RENT = "monthly_rent"
    ANNUAL_RENT = "annual_rent"
    UNSPECIFIED = "unspecified"


class EvidenceRef(BaseModel):
    """Pointer from a property field back to a supporting passage."""

    passage_id: str
    document_id: str
    canonical_url: str
    note: str | None = None


class Property(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)

    id: str = Field(description="Stable application id, e.g. 'darglobal:dev:trump-tower-jeddah'.")
    source: Source
    source_record_id: str | None = None
    record_type: RecordType

    title: str
    country: str | None = None
    city: str | None = None
    district: str | None = None
    property_type: str | None = None
    transaction_type: TransactionType = TransactionType.UNSPECIFIED

    price_amount: Decimal | None = None
    price_currency: str | None = None
    price_basis: PriceBasis = PriceBasis.UNSPECIFIED
    original_price_text: str | None = None

    bedrooms: int | None = None
    bathrooms: int | None = None
    area_value: Decimal | None = None
    area_unit: str | None = None
    original_area_text: str | None = None

    amenities: list[str] = Field(default_factory=list)
    description: str | None = None
    developer: str | None = None
    completion_or_handover_text: str | None = None

    image_url: str | None = None
    source_url: str
    scraped_at: datetime
    content_hash: str
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @field_serializer("price_amount", "area_value", when_used="json")
    def _decimal_to_str(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class PropertyFacet(BaseModel):
    """A distinct value + count, used to build Explore filter options from data."""

    value: str
    count: int


class PropertyFacets(BaseModel):
    sources: list[PropertyFacet] = Field(default_factory=list)
    cities: list[PropertyFacet] = Field(default_factory=list)
    property_types: list[PropertyFacet] = Field(default_factory=list)
    record_types: list[PropertyFacet] = Field(default_factory=list)
    transaction_types: list[PropertyFacet] = Field(default_factory=list)
    bedrooms: list[PropertyFacet] = Field(default_factory=list)
    currencies: list[PropertyFacet] = Field(default_factory=list)
