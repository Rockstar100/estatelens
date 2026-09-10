import json
from decimal import Decimal
from pathlib import Path

from app.models.property import PriceBasis, RecordType, TransactionType
from app.scrapers import wasalt

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))["data"]


def test_build_from_api_sale_listing():
    url = "https://wasalt.sa/en/property/sale/apartment-135-sqm-with-2-bedrooms-5743817"
    page = wasalt.build_from_api(url, _load("wasalt_sale.json"))
    assert len(page.properties) == 1
    p = page.properties[0]
    assert p.record_type == RecordType.LISTING
    assert p.transaction_type == TransactionType.SALE
    assert p.source_record_id == "5743817"
    assert p.city == "Qatif"
    assert p.district == "Om Al Sahek"
    assert p.bedrooms == 2
    assert p.bathrooms == 3
    assert p.area_value == Decimal("135")
    assert p.property_type == "apartment"
    # this particular listing has no sale price in the source -> stays None
    assert p.price_amount is None
    assert p.price_currency is None
    assert p.price_basis == PriceBasis.UNSPECIFIED
    assert p.source_url == url
    # every property field claim is backed by a passage
    assert p.evidence
    assert all(e.passage_id.startswith(page.document.id) for e in p.evidence)


def test_build_from_api_rent_listing_has_annual_basis_and_price():
    url = "https://wasalt.sa/en/property/rent/3-bedrooms-apartment-rent-140463"
    page = wasalt.build_from_api(url, _load("wasalt_rent.json"))
    p = page.properties[0]
    assert p.transaction_type == TransactionType.RENT
    assert p.price_amount == Decimal("35000")
    assert p.price_currency == "SAR"
    assert p.price_basis in (PriceBasis.ANNUAL_RENT, PriceBasis.MONTHLY_RENT)
    assert p.bedrooms == 3


def test_is_pdp_and_id_parsing():
    assert wasalt.is_pdp("https://wasalt.sa/en/property/sale/x-5")
    assert not wasalt.is_pdp("https://wasalt.sa/en/properties-for-sale-in-riyadh")
    assert wasalt.property_id_from_url("https://wasalt.sa/en/property/rent/a-b-c-140463") == "140463"


def test_image_from_classification_data():
    data = {
        "id": 5856589,
        "classificationData": [
            {"classificationName": "empty_room", "name": "aaaa.webp"},
            {"classificationName": "facade", "name": "c8716042-91f6-465f-9a80-41890dd1d2ca.webp"},
        ],
        "propertyInfo": {},
    }
    url = wasalt._image_from_api_payload(data)
    assert url is not None
    assert "5856589" in url
    assert "c8716042-91f6-465f-9a80-41890dd1d2ca.webp" in url
    assert url.startswith("https://imagedelivery.net/")


def test_missing_price_never_becomes_zero():
    data = _load("wasalt_sale.json")
    data["propertyInfo"]["salePrice"] = None
    data["propertyInfo"]["conversionPrice"] = None
    p = wasalt.build_from_api("https://wasalt.sa/en/property/sale/x-1", data).properties[0]
    assert p.price_amount is None

