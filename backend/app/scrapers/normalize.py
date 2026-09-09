"""Turn messy page text into normalized values. Unknown -> None, never 0."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from app.models.property import PriceBasis

_CURRENCY_MAP = {
    "aed": "AED", "د.إ": "AED", "dhs": "AED", "dirham": "AED",
    "sar": "SAR", "sr": "SAR", "ريال": "SAR", "﷼": "SAR", "ر.س": "SAR", "riyal": "SAR",
    "usd": "USD", "$": "USD", "us$": "USD", "dollar": "USD",
    "gbp": "GBP", "£": "GBP", "pound": "GBP",
    "eur": "EUR", "€": "EUR", "euro": "EUR",
    "qar": "QAR",
}

_MULT = {
    "k": Decimal(1_000), "thousand": Decimal(1_000),
    "m": Decimal(1_000_000), "mn": Decimal(1_000_000), "million": Decimal(1_000_000),
    "b": Decimal(1_000_000_000), "bn": Decimal(1_000_000_000), "billion": Decimal(1_000_000_000),
    "cr": Decimal(10_000_000), "crore": Decimal(10_000_000),
    "lac": Decimal(100_000), "lakh": Decimal(100_000),
}

_BOILERPLATE_PATTERNS = [
    re.compile(r"(?is)we use cookies.*?(accept|agree|got it|preferences)"),
    re.compile(r"(?is)this website uses cookies.*?(policy|settings)\.?"),
    re.compile(r"(?im)^\s*(home|menu|search|sign in|log in|register|contact us)\s*$"),
    re.compile(r"(?is)subscribe to (our )?newsletter.*?$"),
    re.compile(r"(?is)all rights reserved.*?$"),
    re.compile(r"(?is)follow us on.*?$"),
]

_WS = re.compile(r"[ \t ]+")
_MULTINL = re.compile(r"\n{3,}")


def slugify(value: str, max_len: int = 80) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:max_len] or "item"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def clean_text(text: str) -> str:
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(" ", text)
    lines = []
    seen_recent: list[str] = []
    for raw in text.splitlines():
        line = _WS.sub(" ", raw).strip()
        if not line:
            lines.append("")
            continue
        # drop immediate duplicate nav lines
        if line in seen_recent[-4:]:
            continue
        seen_recent.append(line)
        lines.append(line)
    out = "\n".join(lines)
    return _MULTINL.sub("\n\n", out).strip()


def _to_decimal(raw: str) -> Decimal | None:
    raw = raw.replace(",", "").replace(" ", "").strip()
    try:
        d = Decimal(raw)
        return d if d > 0 else None
    except (InvalidOperation, ValueError):
        return None


def detect_currency(text: str) -> str | None:
    low = text.lower()
    for token, code in _CURRENCY_MAP.items():
        if token in low:
            return code
    m = re.search(r"\b([A-Z]{3})\b", text)
    if m and m.group(1) in {"AED", "SAR", "USD", "GBP", "EUR", "QAR"}:
        return m.group(1)
    return None


def detect_basis(text: str) -> PriceBasis:
    low = text.lower()
    if re.search(r"per\s*month|/\s*month|monthly|/\s*mo\b|شهري", low):
        return PriceBasis.MONTHLY_RENT
    if re.search(r"per\s*year|/\s*year|/\s*yr\b|yearly|annually|per\s*annum|p\.a\.|سنوي", low):
        return PriceBasis.ANNUAL_RENT
    if re.search(r"starting (from|at)|from\s*(aed|sar|usd|gbp|eur|\$|£|€)|prices? from|abfrom", low):
        return PriceBasis.STARTING
    if re.search(r"\btotal\b|full price|asking price", low):
        return PriceBasis.TOTAL
    return PriceBasis.UNSPECIFIED


def parse_price(text: str | None) -> tuple[Decimal | None, str | None, PriceBasis, str | None]:
    """Returns (amount, currency, basis, original_text). Any part may be None."""
    if not text:
        return None, None, PriceBasis.UNSPECIFIED, None
    original = " ".join(text.split())[:160]
    currency = detect_currency(original)
    basis = detect_basis(original)

    m = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|mn|million|b|bn|billion|cr|crore|lac|lakh)?",
        original,
        re.I,
    )
    if not m:
        return None, currency, basis, original
    amount = _to_decimal(m.group(1))
    if amount is None:
        return None, currency, basis, original
    suffix = (m.group(2) or "").lower()
    if suffix in _MULT:
        amount *= _MULT[suffix]
    # guard against obvious non-prices: too small to be a real property price,
    # or an absurd figure from a mis-parse (no real listing is > ~100 billion).
    if amount < 100 or amount > Decimal("1e11"):
        return None, currency, basis, original
    return amount, currency, basis, original


def parse_area(text: str | None) -> tuple[Decimal | None, str | None, str | None]:
    if not text:
        return None, None, None
    original = " ".join(text.split())[:120]
    m = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*(sq\.?\s*(?:ft|feet|foot|m|meters?|metres?)|sqft|sqm|m2|m²|ft2|ft²|square\s*(?:feet|meters?|metres?))",
        original,
        re.I,
    )
    if not m:
        return None, None, original
    value = _to_decimal(m.group(1))
    unit_raw = m.group(2).lower().replace(".", "").replace(" ", "")
    unit = "sqft" if ("ft" in unit_raw or "feet" in unit_raw or "foot" in unit_raw) else "sqm"
    return value, unit, original


def parse_int(text: str | None, patterns: tuple[str, ...]) -> int | None:
    if not text:
        return None
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                n = int(m.group(1))
                if 0 <= n <= 60:
                    return n
            except (ValueError, IndexError):
                continue
    return None


def parse_bedrooms(text: str | None) -> int | None:
    if text and re.search(r"\bstudio\b", text, re.I):
        return 0
    return parse_int(text, (r"(\d+)\s*(?:bed|bedroom|bedrooms|br|bhk)\b",))


def parse_bathrooms(text: str | None) -> int | None:
    return parse_int(text, (r"(\d+)\s*(?:bath|bathroom|bathrooms|ba)\b",))


def make_id(source: str, record_type: str, key: str) -> str:
    rt = "dev" if record_type == "development" else "listing"
    return f"{source}:{rt}:{slugify(key, 100)}"


_HEADING_SPLIT = re.compile(r"\n(?=[A-Z][^\n]{0,80}\n)")


def _sentence_windows(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) + 1 > max_chars:
            out.append(buf.strip())
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf.strip())
    return out


def chunk_passages(cleaned_text: str, *, max_chars: int = 900, min_chars: int = 120) -> list[tuple[str | None, str]]:
    """Split cleaned text into passages, keeping a preceding short line as a heading."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", cleaned_text) if p.strip()]
    # Pages whose text has no blank-line paragraphs (single-newline lists, SPA
    # dumps) collapse to one giant "paragraph"; break those by single newline and,
    # failing that, by sentence windows so we don't lose most of the content.
    if len(paras) <= 1 and len(cleaned_text) > max_chars:
        by_line = [p.strip() for p in cleaned_text.split("\n") if p.strip()]
        paras = by_line if len(by_line) > 1 else _sentence_windows(cleaned_text, max_chars)
    chunks: list[tuple[str | None, str]] = []
    buf: list[str] = []
    heading: str | None = None
    size = 0
    for para in paras:
        if len(para) <= 70 and not para.endswith((".", "!", "?")) and len(para.split()) <= 10:
            if buf:
                chunks.append((heading, " ".join(buf)))
                buf, size = [], 0
            heading = para
            continue
        buf.append(para)
        size += len(para)
        if size >= max_chars:
            chunks.append((heading, " ".join(buf)))
            buf, size = [], 0
    if buf:
        chunks.append((heading, " ".join(buf)))
    return [(h, t) for h, t in chunks if len(t) >= min_chars] or (
        [(None, cleaned_text[:max_chars])] if len(cleaned_text) >= min_chars else []
    )
