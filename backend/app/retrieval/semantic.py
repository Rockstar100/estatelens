"""In-process semantic search over passage vectors stored in MongoDB.

The corpus is small (hundreds of passages), so the whole vector matrix is loaded
once and cached; a query is embedded and scored with a single dot product
(vectors are unit-normalised, so dot == cosine). This is the "optional semantic
layer" — if no vectors are indexed or the query cannot be embedded, callers get
an empty result and fall back to lexical retrieval.
"""

from __future__ import annotations

import time

import numpy as np

from app.config import get_settings
from app.db import repo
from app.services.embeddings import embed_query
from app.services.logging import get_logger

log = get_logger("estatelens.semantic")

_CACHE_TTL = 300.0


class _VectorIndex:
    def __init__(self) -> None:
        self.ids: list[str] = []
        self.prop_ids: list[str | None] = []
        self.matrix: np.ndarray | None = None  # (n, dim), row-normalised
        self.model: str = ""
        self._loaded_at = 0.0
        self._signature: tuple[int, str] = (0, "")

    def fresh(self, signature: tuple[int, str]) -> bool:
        return (
            self.matrix is not None
            and self._signature == signature
            and (time.monotonic() - self._loaded_at) < _CACHE_TTL
        )

    def load(self, rows: list[dict], model: str, signature: tuple[int, str]) -> None:
        self.ids = [r["_id"] for r in rows]
        self.prop_ids = [r.get("property_id") for r in rows]
        self.matrix = np.asarray([r["embedding"] for r in rows], dtype=np.float32)
        self.model = model
        self._loaded_at = time.monotonic()
        self._signature = signature


_INDEX = _VectorIndex()


async def _load_index() -> _VectorIndex:
    s = get_settings()
    db = repo.get_db()
    q = {
        "active": True,
        "embedding": {"$type": "array"},
        "embedding_model": s.embedding_model,
    }
    total = await db.passages.count_documents(q)
    # Signature changes when the number of indexed vectors or the model changes,
    # so a fresh `embed` run is picked up without a restart.
    signature = (total, s.embedding_model)
    if _INDEX.fresh(signature):
        return _INDEX
    cursor = db.passages.find(q, {"_id": 1, "property_id": 1, "embedding": 1})
    rows = await cursor.to_list(length=5000)
    rows = [r for r in rows if isinstance(r.get("embedding"), list) and r["embedding"]]
    if rows:
        _INDEX.load(rows, s.embedding_model, signature)
    else:
        _INDEX.matrix = None
        _INDEX._signature = signature
        _INDEX._loaded_at = time.monotonic()
    return _INDEX


async def semantic_scores(
    query: str,
    *,
    allowed_property_ids: set[str] | None = None,
    top_k: int = 12,
) -> dict[str, float]:
    """Map passage_id -> cosine similarity (0..1) for the best semantic matches.

    ``allowed_property_ids`` (when given) restricts scoring to passages tied to
    those properties plus source-level passages with no property_id. Returns an
    empty dict when semantic search is unavailable.
    """
    if not get_settings().embeddings_configured:
        return {}
    try:
        index = await _load_index()
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic index load failed", extra={"error": str(exc)[:200]})
        return {}
    if index.matrix is None or not len(index.ids):
        return {}

    qvec = await embed_query(query)
    if not qvec:
        return {}
    q = np.asarray(qvec, dtype=np.float32)
    if q.shape[0] != index.matrix.shape[1]:
        log.warning(
            "semantic dim mismatch",
            extra={"query": int(q.shape[0]), "index": int(index.matrix.shape[1])},
        )
        return {}

    sims = index.matrix @ q  # cosine, both sides unit-normalised
    order = np.argsort(-sims)

    out: dict[str, float] = {}
    for i in order:
        if len(out) >= top_k:
            break
        pid = index.prop_ids[i]
        if allowed_property_ids is not None and pid is not None and pid not in allowed_property_ids:
            continue
        score = float(sims[i])
        if score <= 0.0:
            continue
        out[index.ids[i]] = round(score, 4)
    return out
