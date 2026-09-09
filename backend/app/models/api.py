"""Request / response and streaming-event schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.property import Property

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatContext(BaseModel):
    """Client-supplied conversation state. All fields are advisory and validated."""

    selected_property_ids: list[str] = Field(default_factory=list, max_length=3)
    last_result_ids: list[str] = Field(default_factory=list, max_length=50)
    filters: dict = Field(default_factory=dict)

    @field_validator("selected_property_ids", "last_result_ids")
    @classmethod
    def _clean_ids(cls, v: list[str]) -> list[str]:
        return [s for s in (x.strip() for x in v) if s and len(s) <= 200]


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    context: ChatContext = Field(default_factory=ChatContext)

    @field_validator("messages")
    @classmethod
    def _last_is_user(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if v[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return v


# ---------------------------------------------------------------------------
# Streaming events (our own typed SSE contract)
#
#   event: evidence  -> StreamEvidence   (once, before any delta)
#   event: delta     -> StreamDelta      (zero or more)
#   event: cards     -> StreamCards      (optional, DB-backed property cards)
#   event: done      -> StreamDone       (once, terminal)
#   event: error     -> StreamError      (terminal; may replace done)
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    id: str
    ordinal: int
    source: str
    site: str
    title: str | None
    section_heading: str | None
    excerpt: str
    url: str
    collected_at: datetime


class StreamEvidence(BaseModel):
    type: Literal["evidence"] = "evidence"
    items: list[EvidenceItem]
    retrieval_method: str
    applied_filters: dict = Field(default_factory=dict)


class StreamDelta(BaseModel):
    type: Literal["delta"] = "delta"
    text: str


class StreamCards(BaseModel):
    type: Literal["cards"] = "cards"
    properties: list[Property]


class StreamDone(BaseModel):
    type: Literal["done"] = "done"
    citations: list[str] = Field(default_factory=list)
    property_ids: list[str] = Field(default_factory=list)
    model: str | None = None
    finish_reason: str | None = None
    usage: dict | None = None
    request_id: str | None = None


class StreamError(BaseModel):
    type: Literal["error"] = "error"
    category: Literal[
        "provider_unavailable",
        "quota_exhausted",
        "timeout",
        "bad_request",
        "internal",
        "rate_limited",
    ]
    message: str
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class PropertyListResponse(BaseModel):
    items: list[Property]
    total: int
    page: int
    page_size: int
    has_more: bool
    facets: dict


# ---------------------------------------------------------------------------
# Sources & About
# ---------------------------------------------------------------------------


class SourceCoverage(BaseModel):
    source: str
    site: str
    document_count: int
    property_count: int
    listing_count: int
    development_count: int
    latest_collection: datetime | None
    cities: list[str]
    record_types: list[str]
    extraction_failures: int


class SourcesResponse(BaseModel):
    sources: list[SourceCoverage]
    total_documents: int
    total_properties: int
    total_passages: int
    retrieval_method: str
    model: str
    fallback_model: str
    model_tested_on: str
    coverage_gaps: list[str]
    generated_at: datetime


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    time: datetime


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class ReadinessResponse(BaseModel):
    ready: bool
    checks: list[ReadinessCheck]
    time: datetime
