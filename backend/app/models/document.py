"""Source pages, retrievable passages, and crawl-run bookkeeping."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.property import Source

# Store/serialize enum *values* (plain strings), so `.source` is always "darglobal"
# and never the enum object — matches how Property behaves.
_ENUM_VALUES = ConfigDict(use_enum_values=True)


class ExtractionMethod(str, Enum):
    HTTPX_BS4 = "httpx_bs4"
    JSON_LD = "json_ld"
    CRAWL4AI = "crawl4ai"


class ExtractionStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


class Document(BaseModel):
    """One fetched public page after cleaning."""

    model_config = _ENUM_VALUES

    id: str
    source: Source
    canonical_url: str
    title: str | None = None
    cleaned_text: str
    fetched_at: datetime
    content_hash: str
    extraction_method: ExtractionMethod
    extraction_status: ExtractionStatus
    language: str = "en"
    http_status: int | None = None


class Passage(BaseModel):
    """A retrievable chunk of a document."""

    model_config = _ENUM_VALUES

    id: str
    document_id: str
    property_id: str | None = None
    source: Source
    canonical_url: str
    page_title: str | None = None
    section_heading: str | None = None
    text: str
    collected_at: datetime
    content_hash: str
    language: str = "en"
    # Semantic index (optional). ``embedding`` is a unit-normalised float vector;
    # ``embedding_hash`` ties it to the exact text it was built from so a content
    # change invalidates it.
    embedding_model: str | None = None
    embedding: list[float] | None = None
    embedding_hash: str | None = None
    # Set False when a newer version of the parent document supersedes this chunk.
    active: bool = True


class SkippedPage(BaseModel):
    url: str
    reason: str


class FailedPage(BaseModel):
    url: str
    error: str


class CrawlRun(BaseModel):
    model_config = _ENUM_VALUES

    id: str
    source: Source
    started_at: datetime
    finished_at: datetime | None = None
    attempted_urls: list[str] = Field(default_factory=list)
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[SkippedPage] = Field(default_factory=list)
    failed: list[FailedPage] = Field(default_factory=list)
    coverage_summary: dict = Field(default_factory=dict)
