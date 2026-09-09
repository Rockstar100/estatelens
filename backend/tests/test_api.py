"""Public API contract tests. Uses the local MongoDB (test database) and a
mocked OpenRouter stream so no quota is consumed.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

os.environ.setdefault("MONGODB_DATABASE", "estatelens_apitest")


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health_needs_no_quota(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_reports_checks(client):
    r = client.get("/api/readiness")
    assert r.status_code in (200, 503)
    names = {c["name"] for c in r.json()["checks"]}
    assert {"mongodb", "openrouter_config", "indexed_data"} <= names


def test_properties_rejects_bad_pagination(client):
    assert client.get("/api/properties?page_size=999").status_code == 422
    assert client.get("/api/properties?bedrooms=-1").status_code == 422


def test_properties_ok_shape(client):
    r = client.get("/api/properties?page_size=5")
    assert r.status_code == 200
    body = r.json()
    assert {"items", "total", "page", "has_more", "facets"} <= body.keys()


def test_unknown_property_is_404(client):
    assert client.get("/api/properties/does-not-exist").status_code == 404


def test_chat_validation_requires_user_last(client):
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "assistant", "content": "hi"}], "context": {}},
    )
    assert r.status_code == 422


def test_chat_streams_error_event_when_inference_unconfigured(client, monkeypatch):
    # No OPENROUTER_API_KEY in the test env -> the stream must still return
    # evidence and then a clean error event (never a fake answer).
    with client.stream(
        "POST",
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}], "context": {}},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    types = [e["type"] for e in events]
    assert "evidence" in types
    assert types[-1] == "error"
    assert events[-1]["category"] in ("provider_unavailable", "internal")
