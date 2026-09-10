"""Semantic layer: cosine ranking, blend, and graceful fallback."""

from __future__ import annotations

import math

from app.services import embeddings as emb


def test_embedding_hash_changes_with_text_and_config():
    a = emb.embedding_hash("sea view villa", "m", 768)
    b = emb.embedding_hash("sea view villa", "m", 768)
    c = emb.embedding_hash("sea view villa", "m", 384)
    d = emb.embedding_hash("golf villa", "m", 768)
    assert a == b
    assert a != c and a != d


def test_normalise_unit_length():
    v = emb._normalise([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)
    assert emb._normalise([0.0, 0.0]) == [0.0, 0.0]


async def test_semantic_scores_empty_when_not_configured(monkeypatch):
    from app.config import get_settings
    from app.retrieval import semantic

    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(s, "semantic_retrieval", True, raising=False)
    assert await semantic.semantic_scores("anything") == {}


async def test_semantic_scores_ranks_by_cosine(monkeypatch):
    from app.config import get_settings
    from app.retrieval import semantic

    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(s, "semantic_retrieval", True, raising=False)

    # Fake 2-D vector index: p_near points the same way as the query, p_far opposite.
    idx = semantic._VectorIndex()
    idx.ids = ["p_near", "p_far", "p_side"]
    idx.prop_ids = [None, None, None]
    import numpy as np

    idx.matrix = np.asarray(
        [[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]], dtype=np.float32
    )
    idx._loaded_at = 1e18  # never expire
    idx._signature = (3, s.embedding_model)

    async def fake_load():
        return idx

    monkeypatch.setattr(semantic, "_load_index", fake_load)

    async def fake_embed_query(_q):
        return [1.0, 0.0]

    monkeypatch.setattr(semantic, "embed_query", fake_embed_query)

    scores = await semantic.semantic_scores("q")
    assert list(scores) and list(scores)[0] == "p_near"
    assert "p_far" not in scores  # negative cosine dropped
    assert scores["p_near"] > scores.get("p_side", 0.0)
