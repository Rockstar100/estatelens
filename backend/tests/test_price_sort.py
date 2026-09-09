"""Price sort must place priced records in order and unpriced (null) ones last,
in both directions. Uses a temporary collection via the shared client.
"""

from decimal import Decimal

import pytest
from bson.decimal128 import Decimal128

from tests.conftest import require_test_db

pytestmark = pytest.mark.integration


@pytest.fixture
async def seeded():
    require_test_db()
    from app.db import client, repo

    await client.connect()
    db = client.get_db()
    await db.properties.delete_many({})
    rows = [
        {"_id": "p:a", "id": "p:a", "title": "cheap", "price_amount": Decimal128(Decimal("100000")),
         "source": "wasalt", "record_type": "listing", "source_url": "http://x", "scraped_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
         "content_hash": "h", "transaction_type": "sale", "price_basis": "total", "amenities": [], "evidence": []},
        {"_id": "p:b", "id": "p:b", "title": "pricey", "price_amount": Decimal128(Decimal("900000")),
         "source": "wasalt", "record_type": "listing", "source_url": "http://x", "scraped_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
         "content_hash": "h", "transaction_type": "sale", "price_basis": "total", "amenities": [], "evidence": []},
        {"_id": "p:c", "id": "p:c", "title": "unpriced", "price_amount": None,
         "source": "darglobal", "record_type": "development", "source_url": "http://x", "scraped_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
         "content_hash": "h", "transaction_type": "sale", "price_basis": "unspecified", "amenities": [], "evidence": []},
    ]
    await db.properties.insert_many(rows)
    yield repo
    await db.properties.delete_many({})
    await client.disconnect()


async def test_price_asc_nulls_last(seeded):
    items, total = await seeded.query_properties({}, page=1, page_size=10, sort=[("price_amount", 1)])
    assert total == 3
    ids = [p.id for p in items]
    assert ids == ["p:a", "p:b", "p:c"]  # cheap, pricey, then the null


async def test_price_desc_nulls_last(seeded):
    items, _ = await seeded.query_properties({}, page=1, page_size=10, sort=[("price_amount", -1)])
    ids = [p.id for p in items]
    assert ids == ["p:b", "p:a", "p:c"]  # pricey, cheap, then the null
