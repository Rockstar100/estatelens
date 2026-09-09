"""Client-supplied chat context must never break a turn or smuggle Mongo
operators, and a valid prior-turn filter must carry forward."""

from decimal import Decimal

import pytest

from app.retrieval.filters import PropertyFilter
from app.retrieval.nlu import merge_filters
from app.retrieval.pipeline import _safe_context_filter


@pytest.mark.parametrize(
    "raw",
    [
        {"$where": "1==1"},
        {"city": {"$ne": None}},
        {"bedrooms": {"$gt": 0}},
        {"__proto__": {"x": 1}},
        "not a dict",
        ["also", "not"],
        None,
        123,
        {"budget_max": "not-a-number"},
        {"bedrooms": 999},
        {"sort": "; drop table"},
    ],
)
def test_hostile_context_never_raises_and_drops_bad_keys(raw):
    f = _safe_context_filter(raw)
    assert isinstance(f, PropertyFilter)
    d = f.model_dump(exclude_none=True, exclude_defaults=True)
    assert all(not isinstance(v, dict) for v in d.values())
    assert "$where" not in d and "__proto__" not in d


def test_valid_context_survives():
    f = _safe_context_filter({"city": "Riyadh", "bedrooms": 3, "transaction_type": "sale"})
    d = f.model_dump(exclude_none=True, exclude_defaults=True)
    assert d["city"] == "Riyadh" and d["bedrooms"] == 3


def test_partial_valid_keeps_good_drops_bad():
    f = _safe_context_filter({"city": "Jeddah", "bedrooms": {"$gt": 1}, "budget_max": "x"})
    d = f.model_dump(exclude_none=True, exclude_defaults=True)
    assert d.get("city") == "Jeddah"
    assert "bedrooms" not in d and "budget_max" not in d


def test_prior_turn_filter_carries_and_refines():
    base = _safe_context_filter(
        {"source": "wasalt", "city": "Riyadh", "transaction_type": "sale", "property_type": "apartment"}
    )
    from app.retrieval.nlu import extract_filter

    turn = extract_filter("what about only 3 bedrooms", [])
    merged = merge_filters(base, turn)
    d = merged.model_dump(exclude_none=True, exclude_defaults=True)
    assert d["city"] == "Riyadh"
    assert getattr(d["transaction_type"], "value", d["transaction_type"]) == "sale"
    assert d["bedrooms"] == 3


def test_prior_turn_transaction_can_be_flipped():
    from app.retrieval.nlu import extract_filter

    base = _safe_context_filter({"transaction_type": "sale", "city": "Riyadh"})
    merged = merge_filters(base, extract_filter("now show rentals", []))
    assert getattr(merged.model_dump()["transaction_type"], "value", None) == "rent"
