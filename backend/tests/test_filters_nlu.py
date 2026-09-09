from decimal import Decimal

from bson.decimal128 import Decimal128

from app.models.property import RecordType, Source, TransactionType
from app.retrieval.filters import PropertyFilter, build_mongo_filter
from app.retrieval.nlu import extract_filter, merge_filters, resolve_ordinal_reference


def test_budget_requires_non_null_numeric_price():
    f = PropertyFilter(budget_max=Decimal("2000000"), currency="AED")
    q, _sort, notes = build_mongo_filter(f)
    price = q["price_amount"]
    assert price["$lte"] == Decimal128(Decimal("2000000"))
    assert price["$type"] == "decimal"  # unknown (null) prices excluded
    assert q["price_currency"] == "AED"


def test_budget_without_currency_is_flagged_not_silent():
    f = PropertyFilter(budget_max=Decimal("1000000"))
    _q, _s, notes = build_mongo_filter(f)
    assert any("without a currency" in n for n in notes)


def test_sale_and_rent_never_mixed():
    q, _s, _n = build_mongo_filter(PropertyFilter(transaction_type=TransactionType.RENT))
    assert q["transaction_type"] == "rent"


def test_city_match_is_anchored_and_escaped():
    q, _s, _n = build_mongo_filter(PropertyFilter(city="Riyadh"))
    assert q["city"]["$regex"].startswith("^")
    assert q["city"]["$options"] == "i"


def test_nlu_extracts_structured_intent():
    f = extract_filter(
        "3 bedroom villa for rent in Dubai under 200k AED per year",
        known_cities=["Dubai", "Riyadh"],
    )
    assert f.bedrooms == 3
    assert f.property_type == "villa"
    assert f.transaction_type == TransactionType.RENT
    assert f.city == "Dubai"
    assert f.currency == "AED"
    assert f.budget_max == Decimal("200000")


def test_nlu_source_detection():
    assert extract_filter("what does wasalt say about auctions").source == Source.WASALT
    assert extract_filter("darglobal waterfront projects").source == Source.DARGLOBAL


def test_merge_filters_refines_not_replaces():
    base = PropertyFilter(city="Riyadh", transaction_type=TransactionType.SALE)
    update = PropertyFilter(bedrooms=3)
    merged = merge_filters(base, update)
    assert merged.city == "Riyadh"
    assert merged.bedrooms == 3
    assert merged.transaction_type == TransactionType.SALE


def test_ordinal_reference_resolution():
    ids = ["a", "b", "c", "d"]
    assert resolve_ordinal_reference("compare the first and third", ids) == ["a", "c"]
    assert resolve_ordinal_reference("tell me about the second one", ids) == ["b"]
    assert resolve_ordinal_reference("the last option", ids) == ["d"]
    assert resolve_ordinal_reference("no ordinals here", ids) == []


def test_filter_rejects_unknown_sort():
    assert PropertyFilter(sort="; drop table").sort == "relevance"
