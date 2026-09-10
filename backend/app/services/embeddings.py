"""Text embeddings via Google's Generative Language API (same GEMINI_API_KEY).

Used to build the optional semantic-retrieval layer. Vectors are unit-normalised
so a dot product equals cosine similarity. Every function degrades to ``None`` /
empty rather than raising, so a missing key or a transient API error just falls
back to lexical retrieval.
"""

from __future__ import annotations

import asyncio
import hashlib
import math

import httpx

from app.config import get_settings
from app.services.logging import get_logger

log = get_logger("estatelens.embeddings")

# Google caps batchEmbedContents at 100 requests per call.
_BATCH = 100
_TIMEOUT = 30.0


def embedding_hash(text: str, model: str, dims: int) -> str:
    """Identity of an embedding: the text it was built from + how it was built."""
    h = hashlib.sha256()
    h.update(f"{model}:{dims}:".encode())
    h.update(text.encode("utf-8", "replace"))
    return h.hexdigest()


def _normalise(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    if n <= 1e-12:
        return vec
    return [x / n for x in vec]


async def embed_texts(
    texts: list[str],
    *,
    task_type: str = "RETRIEVAL_DOCUMENT",
    client: httpx.AsyncClient | None = None,
) -> list[list[float]] | None:
    """Return one unit vector per input text, or ``None`` if embeddings are not
    configured or the API failed. Order matches the input."""
    s = get_settings()
    if not s.embeddings_configured or not texts:
        return None

    model = s.embedding_model
    dims = s.embedding_dimensions
    url = f"{s.embedding_base_url.rstrip('/')}/models/{model}:batchEmbedContents"
    owns = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT)
    out: list[list[float]] = []
    try:
        for i in range(0, len(texts), _BATCH):
            chunk = texts[i : i + _BATCH]
            payload = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": t[:8000]}]},
                        "taskType": task_type,
                        "outputDimensionality": dims,
                    }
                    for t in chunk
                ]
            }
            resp = await client.post(url, params={"key": s.gemini_api_key}, json=payload)
            # The free embeddings tier rate-limits aggressively; back off and retry
            # a few times before giving up (and falling back to lexical).
            retries = 0
            while resp.status_code == 429 and retries < 4:
                wait = 5 * (retries + 1)
                log.warning("embed rate-limited, backing off", extra={"wait_s": wait})
                await asyncio.sleep(wait)
                resp = await client.post(url, params={"key": s.gemini_api_key}, json=payload)
                retries += 1
            if resp.status_code >= 400:
                log.warning(
                    "embed request failed",
                    extra={"status": resp.status_code, "body": resp.text[:200]},
                )
                return None
            data = resp.json()
            embs = data.get("embeddings") or []
            if len(embs) != len(chunk):
                log.warning("embed count mismatch", extra={"want": len(chunk), "got": len(embs)})
                return None
            for e in embs:
                vals = e.get("values") or []
                if not vals:
                    return None
                out.append(_normalise([float(x) for x in vals]))
        return out
    except (httpx.HTTPError, ValueError) as exc:  # noqa: BLE001
        log.warning("embed error", extra={"error": str(exc)[:200]})
        return None
    finally:
        if owns:
            await client.aclose()


async def embed_query(text: str) -> list[float] | None:
    vecs = await embed_texts([text], task_type="RETRIEVAL_QUERY")
    return vecs[0] if vecs else None
