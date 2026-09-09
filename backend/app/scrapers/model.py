"""Shared shapes for source adapters."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.document import Document, Passage
from app.models.property import Property


@dataclass
class ExtractedPage:
    document: Document
    passages: list[Passage] = field(default_factory=list)
    properties: list[Property] = field(default_factory=list)
