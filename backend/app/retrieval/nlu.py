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

    # --- source (tolerant of common misspellings) --------------------
    if re.search(r"\bdar\s?global\b|\bdarglob\w*\b|\bdar\s?glob\w*\b", lowered):
        data["source"] = Source.DARGLOBAL
    elif re.search(r"\bwas+a?l+a?t\b|\bwasl?at\b|\bwaslt\b|\bwasal\b", lowered):
        data["source"] = Source.WASALT

    # --- transaction type ------------------------------------------
    # "for sale or for rent" / "sale or rent" asks which applies — do not
    # lock the filter to one side (that drops the named property entirely).
    asking_tx = re.search(
        r"\b(?:for\s+)?sale\s+or\s+(?:for\s+)?rent\b"
        r"|\b(?:for\s+)?rent\s+or\s+(?:for\s+)?sale\b"
        r"|\bsale\s*/\s*rent\b"
        r"|\brent\s*/\s*sale\b",
        lowered,
    )
    if asking_tx:
        pass
    elif re.search(
        r"\b(for rent|to rent|rent(?:al|als|ed|ing)?|leas(?:e|ing)|to let|for hire)\b",
        lowered,
    ):
        data["transaction_type"] = TransactionType.RENT
    elif re.search(
        r"\b(for[- ]sale|to buy|buy(?:ing)?|purchas(?:e|ing)|on sale|to own|"
        r"sale listing|sales? listings?|resale|sale)\b",
        lowered,
    ):
        data["transaction_type"] = TransactionType.SALE

    # --- record type ---------------------------------------------
    if re.search(r"\b(project|development|master community|off[- ]plan)\b", lowered):
        data["record_type"] = RecordType.DEVELOPMENT
    elif re.search(r"\b(listing|unit|specific (?:flat|apartment|villa))\b", lowered):
        data["record_type"] = RecordType.LISTING

    # --- bedrooms ---------------------------------------------
    # Accepts "3 bed", "3-bedroom", "3br", "3 bhk", "3+ bedrooms".
    bed = re.search(r"\b(\d{1,2})\s*(?:\+)?[\s-]*(?:bed(?:room)?s?|br|bhk)\b", lowered)
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
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|m|mn|million|bn|billion)?\b",
        lowered,
    )
    if money:
        amount = _parse_amount(money.group(1), money.group(2))
        if amount and amount > 0:
            data["budget_max"] = amount
    over = re.search(
        r"(?:over|above|more than|at least|from)\s*"
        r"(?:aed|sar|usd|gbp|eur|qar|sr|\$|£)?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|m|mn|million|bn|billion)?\b",
        lowered,
    )
    if over:
        # "at least 3 bedrooms" must not parse as "3 billion" via a bare "b".
        # Only treat as money when a currency marker or magnitude suffix is present,
        # or the number is clearly monetary (>= 1000 without a unit word after).
        raw_n, suf = over.group(1), over.group(2)
        after = lowered[over.end() : over.end() + 16]
        if re.match(r"\s*(bed|br|bhk|bath|sq)", after):
            pass
        else:
            amount = _parse_amount(raw_n, suf)
            if amount and amount > 0:
                # bare small integers without suffix/currency are bedroom-like, skip
                if suf or amount >= 1000:
                    data["budget_min"] = amount

    # --- city -----------------------------------------------
    for city in known_cities or []:
        if city and re.search(rf"\b{re.escape(city.lower())}\b", lowered):
            data["city"] = city
            break

    # --- superlatives -> sort ------------------------------
    if re.search(r"\b(cheapest|lowest[- ]?priced?|least expensive|most affordable|budget)\b", lowered):
        data["sort"] = "price_asc"
    elif re.search(r"\b(most expensive|priciest|highest[- ]?priced?|dearest|top[- ]?priced?)\b", lowered):
        data["sort"] = "price_desc"
    elif re.search(r"\b(newest|latest|most recent|recently (?:added|collected))\b", lowered):
        data["sort"] = "newest"
    elif re.search(r"\b(sort|order)(ed)? by (lowest |ascending )?price\b", lowered):
        data["sort"] = "price_asc"
    elif re.search(r"\b(largest|biggest|most spacious|widest|greatest area|by (?:size|area))\b", lowered):
        data["sort"] = "area_desc"
    elif re.search(r"\b(smallest|most compact|tiniest|least (?:area|space))\b", lowered):
        data["sort"] = "area_asc"

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
    # Exact bedroom count and a minimum are mutually exclusive — keep the latest.
    if update.bedrooms is not None:
        merged["bedrooms_min"] = None
    if update.bedrooms_min is not None and update.bedrooms is None:
        merged["bedrooms"] = None
    return PropertyFilter.model_validate(merged)
