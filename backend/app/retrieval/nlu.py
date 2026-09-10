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
    # bare "b" omitted — it matches the start of "bedrooms"
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}

_CURRENCY_WORDS = {
    "aed": "AED", "dirham": "AED", "dirhams": "AED",
    "sar": "SAR", "riyal": "SAR", "riyals": "SAR",
    "usd": "USD", "dollar": "USD", "dollars": "USD",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
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

_UNIT_AFTER_AMOUNT = re.compile(r"\s*(bed|br|bhk|bath|sq|m2|metre|meter|year|month)")


def _parse_amount(raw: str, suffix: str | None) -> Decimal | None:
    try:
        value = Decimal(raw.replace(",", ""))
    except Exception:
        return None
    if suffix:
        value *= _MULTIPLIERS.get(suffix.lower(), Decimal(1))
    return value


def _looks_like_unit_amount(match: re.Match[str], text: str) -> bool:
    """True when the number is a bed/bath/area count, not money."""
    return bool(_UNIT_AFTER_AMOUNT.match(text[match.end() : match.end() + 16]))


def extract_filter(text: str, known_cities: list[str] | None = None) -> PropertyFilter:
    lowered = f" {text.lower()} "
    data: dict = {}

    # --- source (tolerant of common misspellings) --------------------
    if re.search(r"\bdar\s?global\b|\bdarglob\w*\b|\bdar\s?glob\w*\b", lowered):
        data["source"] = Source.DARGLOBAL
    elif re.search(r"\bwas+a?l+a?t\b|\bwasl?at\b|\bwaslt\b|\bwasal\b", lowered):
        data["source"] = Source.WASALT

    # --- transaction type ------------------------------------------
    asking_tx = re.search(
        r"\b(?:for\s+)?sale\s+or\s+(?:for\s+)?rent\b"
        r"|\b(?:for\s+)?rent\s+or\s+(?:for\s+)?sale\b"
        r"|\bbuy\s+or\s+(?:rent|lease)\b"
        r"|\b(?:rent|lease)\s+or\s+buy\b"
        r"|\bpurchase\s+or\s+(?:rent|lease)\b"
        r"|\bsale\s*(?:/|versus|vs\.?)\s*rent\b"
        r"|\brent\s*(?:/|versus|vs\.?)\s*sale\b",
        lowered,
    )
    if asking_tx:
        pass
    elif re.search(
        r"\b(for rent|to rent|rentals?|renting|leas(?:e|ing)|to let|for hire)\b",
        lowered,
    ):
        data["transaction_type"] = TransactionType.RENT
    elif re.search(
        r"\b(for[- ]sale|to buy|buy(?:ing)?|purchas(?:e|ing)|on sale|to own|"
        r"sale listing|sales? listings?|resale)\b",
        lowered,
    ):
        data["transaction_type"] = TransactionType.SALE
    # Bare "sale" / "rented" alone are too ambiguous ("sale price", "who rented").

    # --- record type ---------------------------------------------
    if re.search(r"\b(project|development|master community|off[- ]plan)\b", lowered):
        data["record_type"] = RecordType.DEVELOPMENT
    elif re.search(r"\b(listings?|specific (?:flat|apartment|villa))\b", lowered):
        # Bare "unit" is too common in development copy ("unit mix").
        data["record_type"] = RecordType.LISTING

    # --- bedrooms ---------------------------------------------
    bed = re.search(r"\b(\d{1,2})\s*(?:\+)?[\s-]*(?:bed(?:room)?s?|br|bhk)\b", lowered)
    if bed:
        n = int(bed.group(1))
        if re.search(rf"{bed.group(1)}\s*\+", lowered) or "at least" in lowered or "or more" in lowered:
            data["bedrooms_min"] = n
        else:
            data["bedrooms"] = n
    elif re.search(r"\bstudio\b", lowered):
        data["bedrooms"] = 0

    # --- property type -----------------------------------------
    for pt in _PROPERTY_TYPES:
        if re.search(rf"\b{re.escape(pt)}s?\b", lowered):
            data["property_type"] = pt
            break

    # --- currency (word boundaries — avoid "europe" → EUR) ------
    for word, code in _CURRENCY_WORDS.items():
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered):
            data["currency"] = code
            break
    if "$" in text:
        data.setdefault("currency", "USD")
    if "£" in text:
        data.setdefault("currency", "GBP")

    # --- budget ---------------------------------------------
    money = re.search(
        r"(?:under|below|less than|up to|max(?:imum)?|budget of|around|about)\s*"
        r"(?:aed|sar|usd|gbp|eur|qar|sr|\$|£)?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|m|mn|million|bn|billion)?\b",
        lowered,
    )
    if money and not _looks_like_unit_amount(money, lowered):
        amount = _parse_amount(money.group(1), money.group(2))
        if amount and amount > 0 and (money.group(2) or amount >= 1000 or data.get("currency")):
            data["budget_max"] = amount

    over = re.search(
        r"(?:over|above|more than|at least|from)\s*"
        r"(?:aed|sar|usd|gbp|eur|qar|sr|\$|£)?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|thousand|m|mn|million|bn|billion)?\b",
        lowered,
    )
    if over and not _looks_like_unit_amount(over, lowered):
        amount = _parse_amount(over.group(1), over.group(2))
        if amount and amount > 0 and (over.group(2) or amount >= 1000 or data.get("currency")):
            data["budget_min"] = amount

    # --- city -----------------------------------------------
    for city in known_cities or []:
        if city and re.search(rf"\b{re.escape(city.lower())}\b", lowered):
            data["city"] = city
            break

    # --- superlatives -> sort ------------------------------
    if re.search(
        r"\b(cheapest|lowest[- ]?priced?|least expensive|most affordable|budget[- ]friendly)\b",
        lowered,
    ):
        data["sort"] = "price_asc"
    elif re.search(r"\b(most expensive|priciest|highest[- ]?priced?|dearest|top[- ]?priced?)\b", lowered):
        data["sort"] = "price_desc"
    elif re.search(r"\b(newest|latest|most recent|recently (?:added|collected))\b", lowered):
        data["sort"] = "newest"
    elif re.search(r"\b(sort|order)(ed)? by (lowest |ascending )?price\b", lowered):
        data["sort"] = "price_asc"
    elif re.search(
        r"\b(largest|biggest|most spacious|widest|greatest area|by (?:size|area))\b",
        lowered,
    ) and not re.search(r"\b(city|cities|country|countries|market|coverage)\b", lowered):
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
        if not re.search(
            rf"\b(?:the|this|that)\s+{re.escape(word)}\b"
            rf"|\b{re.escape(word)}\s+(?:one|result|listing|property|project|option)\b"
            rf"|\b(?:and|,)\s+{re.escape(word)}\b"
            rf"|\b#{idx + 1}\b",
            lowered,
        ):
            continue
        if re.search(
            rf"\b{re.escape(word)}\s+(?:bedroom|bath|time|week|month|year|day|"
            rf"floor|storey|story|level|half|quarter|prize|place)\b",
            lowered,
        ):
            continue
        try:
            picked.append(ordered_ids[idx])
        except IndexError:
            continue
    seen: set[str] = set()
    return [i for i in picked if not (i in seen or seen.add(i))]


def merge_filters(base: PropertyFilter, update: PropertyFilter) -> PropertyFilter:
    """Follow-up turns refine the previous filter rather than replace it."""
    merged = base.model_dump()
    for key, value in update.model_dump().items():
        if value not in (None, "", "relevance"):
            merged[key] = value
    if update.bedrooms is not None:
        merged["bedrooms_min"] = None
    if update.bedrooms_min is not None and update.bedrooms is None:
        merged["bedrooms"] = None
    return PropertyFilter.model_validate(merged)


def should_carry_filters(user_text: str) -> bool:
    """Whether a follow-up should inherit the previous turn's structured filters."""
    low = user_text.lower()
    if re.search(
        r"\b(start over|reset|clear filters?|show (?:me )?all|never ?mind)\b",
        low,
    ):
        return False
    if re.search(r"\b(compare|versus|vs\.?)\b", low):
        return False
    # Refine phrases keep prior filters ("what about 3 bedrooms").
    if re.search(
        r"\b(what about|how about|only|just|those|these|them|same|still|"
        r"narrow|filter|also show|instead)\b",
        low,
    ) and not re.search(
        r"\b(trump\s+tower|neptune|missoni|astera|ayla|ora|sidr|elenia)\b",
        low,
    ):
        return True
    # Named-project / factual questions should not keep a prior city/source lock.
    if re.search(
        r"\b(what|when|where|who|how|tell me|describe)\b",
        low,
    ) and re.search(
        r"\b(handover|price|cost|located|location|designer|interiors?|"
        r"developer|completion|amenities|tower|project|development)\b",
        low,
    ):
        return False
    if re.search(
        r"\b(trump\s+tower|neptune|missoni|astera|ayla|ora|sidr|elenia)\b",
        low,
    ):
        return False
    return True
