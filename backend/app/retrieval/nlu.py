"""Deterministic natural-language -> typed filter extraction.

This is rule-based on purpose: no model output is trusted to build a query. If a
future version uses the model for extraction, it must still return a
``PropertyFilter`` that is validated here before use.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.models.property import RecordType, Source, TransactionType
from app.retrieval.filters import PropertyFilter

_MULTIPLIERS = {
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "m": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "b": Decimal(1_000_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}

_CURRENCY_WORDS = {
    "aed": "AED", "dirham": "AED", "dirhams": "AED",
    "sar": "SAR", "riyal": "SAR", "riyals": "SAR", "sr": "SAR",
    "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "£": "GBP",
    "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "qar": "QAR",
}

_PROPERTY_TYPES = [
    "villa", "apartment", "penthouse", "townhouse", "studio", "duplex",
    "mansion", "chalet", "plot", "land", "office", "hotel room", "hotel apartment",
]

# Bare cardinals ("one", "two") are too ambiguous ("the second one") — omit them.
_ORDINALS = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
    "last": -1,
}


def _parse_amount(raw: str, suffix: str | None) -> Decimal | None:
    try:
        value = Decimal(raw.replace(",", ""))
    except Exception:
        return None
    if suffix:
        value *= _MULTIPLIERS.get(suffix.lower(), Decimal(1))
    return value


def extract_filter(text: str, known_cities: list[str] | None = None) -> PropertyFilter:
    lowered = f" {text.lower()} "
    data: dict = {}

    # --- source -------------------------------------------------------
    if "darglobal" in lowered or "dar global" in lowered:
        data["source"] = Source.DARGLOBAL
    elif "wasalt" in lowered:
        data["source"] = Source.WASALT

    # --- transaction type ------------------------------------------
    if re.search(
        r"\b(for rent|to rent|rent(?:al|als|ed|ing)?|leas(?:e|ing)|to let|for hire)\b",
        lowered,
    ):
        data["transaction_type"] = TransactionType.RENT
    elif re.search(
        r"\b(for sale|to buy|buy(?:ing)?|purchas(?:e|ing)|on sale|to own)\b", lowered
    ):
        data["transaction_type"] = TransactionType.SALE

    # --- record type ---------------------------------------------
    if re.search(r"\b(project|development|master community|off[- ]plan)\b", lowered):
        data["record_type"] = RecordType.DEVELOPMENT
    elif re.search(r"\b(listing|unit|specific (?:flat|apartment|villa))\b", lowered):
        data["record_type"] = RecordType.LISTING

    # --- bedrooms ---------------------------------------------
    bed = re.search(r"\b(\d{1,2})\s*(?:\+)?\s*(?:bed|bedroom|bedrooms|br|bhk)\b", lowered)
    if bed:
        n = int(bed.group(1))
        if re.search(rf"{bed.group(1)}\s*\+", lowered) or "at least" in lowered or "or more" in lowered:
            data["bedrooms_min"] = n
        else:
            data["bedrooms"] = n
    elif "studio" in lowered:
        data["bedrooms"] = 0

    # --- property type -----------------------------------------
    for pt in _PROPERTY_TYPES:
        if re.search(rf"\b{re.escape(pt)}s?\b", lowered):
            data["property_type"] = pt
            break

    # --- currency ---------------------------------------------
    for word, code in _CURRENCY_WORDS.items():
        if word in lowered:
            data["currency"] = code
            break

    # --- budget ---------------------------------------------
    money = re.search(
        r"(?:under|below|less than|up to|max(?:imum)?|budget of|around|about)\s*"
        r"(?:aed|sar|usd|gbp|eur|qar|sr|\$|£)?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|m|mn|million|b|bn|billion)?",
        lowered,
    )
    if money:
        amount = _parse_amount(money.group(1), money.group(2))
        if amount and amount > 0:
            data["budget_max"] = amount
    over = re.search(
        r"(?:over|above|more than|at least|from)\s*"
        r"(?:aed|sar|usd|gbp|eur|qar|sr|\$|£)?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|m|mn|million|b|bn|billion)?",
        lowered,
    )
    if over:
        amount = _parse_amount(over.group(1), over.group(2))
        if amount and amount > 0:
            data["budget_min"] = amount

    # --- city -----------------------------------------------
    for city in known_cities or []:
        if city and re.search(rf"\b{re.escape(city.lower())}\b", lowered):
            data["city"] = city
            break

    return PropertyFilter.model_validate(data)


def resolve_ordinal_reference(text: str, ordered_ids: list[str]) -> list[str]:
    """Map 'the first and third' / 'the second one' onto previously shown result ids."""
    if not ordered_ids:
        return []
    lowered = text.lower()
    picked: list[str] = []
    for word, idx in _ORDINALS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            try:
                picked.append(ordered_ids[idx])
            except IndexError:
                continue
    # de-dupe, preserve order
    seen: set[str] = set()
    return [i for i in picked if not (i in seen or seen.add(i))]


def merge_filters(base: PropertyFilter, update: PropertyFilter) -> PropertyFilter:
    """Follow-up turns refine the previous filter rather than replace it."""
    merged = base.model_dump()
    for key, value in update.model_dump().items():
        if value not in (None, "", "relevance"):
            merged[key] = value
    return PropertyFilter.model_validate(merged)
