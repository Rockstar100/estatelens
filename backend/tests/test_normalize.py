from decimal import Decimal

import pytest

from app.models.property import PriceBasis
from app.scrapers.normalize import (
    chunk_passages,
    clean_text,
    make_id,
    parse_area,
    parse_bedrooms,
    parse_price,
)


@pytest.mark.parametrize(
    "text,amount,currency,basis",
    [
        ("Starting from AED 2,500,000", Decimal("2500000"), "AED", PriceBasis.STARTING),
        ("SAR 750,000", Decimal("750000"), "SAR", PriceBasis.UNSPECIFIED),
        ("Price from £1.2 million", Decimal("1200000"), "GBP", PriceBasis.STARTING),
        ("35000 ر.س per year", Decimal("35000"), "SAR", PriceBasis.ANNUAL_RENT),
        ("Contact for price", None, None, PriceBasis.UNSPECIFIED),
        ("", None, None, PriceBasis.UNSPECIFIED),
    ],
)
def test_parse_price(text, amount, currency, basis):
    a, c, b, original = parse_price(text)
    assert a == amount
    assert c == currency
    assert b == basis
    if text:
        assert original is not None


def test_parse_price_never_zero_for_unknown():
    a, *_ = parse_price("Price on request")
    assert a is None  # not Decimal(0)


def test_parse_area():
    v, unit, original = parse_area("Built-up area 164.95 sqm")
    assert v == Decimal("164.95")
    assert unit == "sqm"
    v2, unit2, _ = parse_area("1,200 sq ft")
    assert v2 == Decimal("1200")
    assert unit2 == "sqft"
    assert parse_area(None) == (None, None, None)


def test_parse_bedrooms_studio_is_zero_not_none():
    assert parse_bedrooms("Cosy studio apartment") == 0
    assert parse_bedrooms("3 bedroom villa") == 3
    assert parse_bedrooms("great location") is None


def test_clean_text_strips_cookie_boilerplate():
    raw = "We use cookies to improve your experience. Accept\n\nReal content about a villa."
    out = clean_text(raw)
    assert "cookies" not in out.lower()
    assert "Real content about a villa." in out


def test_make_id_stable():
    a = make_id("wasalt", "listing", "apartment-135-sqm-5743817")
    b = make_id("wasalt", "listing", "apartment-135-sqm-5743817")
    assert a == b == "wasalt:listing:apartment-135-sqm-5743817"


def test_chunk_passages_non_empty():
    text = "Heading One\n\n" + ("A sentence about the property. " * 20) + "\n\nAnother paragraph here that is long enough to keep."
    chunks = chunk_passages(text)
    assert chunks
    assert all(len(t) >= 120 for _, t in chunks)
