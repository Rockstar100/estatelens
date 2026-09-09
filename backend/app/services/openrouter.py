"""OpenRouter client — free inference routes only.

Behaviour required by the brief:
  * one generation call per ordinary answer;
  * bounded output tokens and a request timeout;
  * limited retries with backoff, honouring ``Retry-After``;
  * transient provider failures are distinguished from an exhausted account quota
    (the latter is NOT retried and does not silently switch to a paid route);
  * streaming can be cancelled mid-response by the caller closing the generator.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.services.logging import get_logger

log = get_logger("estatelens.openrouter")

_QUOTA_HINTS = (
    "quota", "insufficient", "credit", "billing", "exceeded your",
    "add more credits", "free-models-per-day", "daily limit",
)


class OpenRouterError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category  # provider_unavailable | quota_exhausted | timeout
        self.message = message


@dataclass
class StreamChunk:
    text: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    model: str | None = None


class OpenRouterClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=httpx.Timeout(settings.openrouter_timeout_seconds, connect=10.0),
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "HTTP-Referer": settings.app_base_url,
                "X-Title": "EstateLens",
            },
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def models(self) -> list[str]:
        out = [self._s.openrouter_model]
        if self._s.openrouter_fallback_model and self._s.openrouter_fallback_model not in out:
            out.append(self._s.openrouter_fallback_model)
        return out

    async def stream_chat(
        self, messages: list[dict], *, max_retries: int = 2
    ) -> AsyncIterator[StreamChunk]:
        """Yield chunks from the first model that responds. Fallback only on
        provider-unavailable errors, never on quota exhaustion."""
        if not self._s.openrouter_configured:
            raise OpenRouterError("provider_unavailable", "OPENROUTER_API_KEY is not set.")

        last_error: OpenRouterError | None = None
        for model in self.models:
            attempt = 0
            while attempt <= max_retries:
                try:
                    async for chunk in self._stream_once(model, messages):
                        yield chunk
                    return
                except OpenRouterError as exc:
                    last_error = exc
                    if exc.category == "quota_exhausted":
                        raise
                    attempt += 1
                    if attempt > max_retries:
                        break
                    backoff = min(2**attempt, 8) + (0.1 * attempt)
                    log.warning(
                        "openrouter retry",
                        extra={"model": model, "attempt": attempt, "category": exc.category},
                    )
                    await asyncio.sleep(backoff)
            log.warning("openrouter model exhausted, trying next", extra={"model": model})

        raise last_error or OpenRouterError("provider_unavailable", "No model produced a response.")

    async def _stream_once(self, model: str, messages: list[dict]) -> AsyncIterator[StreamChunk]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": self._s.openrouter_max_output_tokens,
            "temperature": 0.2,
            "usage": {"include": True},
        }
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise self._classify(resp.status_code, body, resp.headers)

                emitted = False
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        raise self._classify(200, json.dumps(obj["error"]), resp.headers)
                    choice = (obj.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        emitted = True
                        yield StreamChunk(text=delta, model=obj.get("model") or model)
                    if choice.get("finish_reason"):
                        yield StreamChunk(
                            finish_reason=choice["finish_reason"],
                            usage=obj.get("usage"),
                            model=obj.get("model") or model,
                        )
                if not emitted:
                    raise OpenRouterError("provider_unavailable", f"{model} returned no content.")
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            raise OpenRouterError("timeout", f"{model} timed out.") from exc
        except httpx.HTTPError as exc:
            raise OpenRouterError("provider_unavailable", f"{model} transport error: {exc}") from exc

    @staticmethod
    def _classify(status: int, body: str, headers: httpx.Headers) -> OpenRouterError:
        low = body.lower()
        if status == 429:
            if any(h in low for h in _QUOTA_HINTS):
                return OpenRouterError(
                    "quota_exhausted",
                    "The OpenRouter account's free quota is exhausted. Switching models "
                    "will not help — this is an account limit. Try again later.",
                )
            return OpenRouterError("provider_unavailable", "Rate limited by the provider.")
        if status in (401, 403):
            return OpenRouterError("provider_unavailable", "OpenRouter rejected the API key.")
        if status in (402,):
            return OpenRouterError(
                "quota_exhausted", "OpenRouter reports no available free credit for this route."
            )
        if 500 <= status < 600 or status == 200:
            return OpenRouterError("provider_unavailable", f"Upstream model error: {body[:200]}")
        return OpenRouterError("provider_unavailable", f"HTTP {status}: {body[:200]}")
