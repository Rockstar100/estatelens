"""Multi-provider streaming LLM client (OpenRouter · Groq · Gemini).

All three speak an OpenAI-compatible ``/chat/completions`` stream. Order is
controlled by ``LLM_PROVIDER`` (``auto`` tries Groq → Gemini → OpenRouter when
keys are present). Quota exhaustion on one provider falls through to the next.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.services.logging import get_logger

log = get_logger("estatelens.llm")

_QUOTA_HINTS = (
    "quota", "insufficient", "credit", "billing", "exceeded your",
    "add more credits", "free-models-per-day", "daily limit", "resource_exhausted",
    "tokens per day", "tpd",
)
_RATE_LIMIT_HINTS = (
    "rate limit", "rate_limit", "too many requests", "tpm", "rpm",
)


class LLMError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category  # provider_unavailable | quota_exhausted | timeout
        self.message = message


# Back-compat alias used by chat.py / tests
OpenRouterError = LLMError


@dataclass
class StreamChunk:
    text: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    model: str | None = None


@dataclass
class _Provider:
    name: str
    base_url: str
    api_key: str
    models: list[str]
    extra_headers: dict[str, str]
    # OpenRouter accepts a reasoning.exclude flag; others ignore unknown fields
    # but we only send it for OpenRouter to stay tidy.
    send_reasoning_exclude: bool = False


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._clients: list[httpx.AsyncClient] = []

    async def aclose(self) -> None:
        for c in self._clients:
            await c.aclose()
        self._clients.clear()

    def _providers(self) -> list[_Provider]:
        s = self._s
        groq = _Provider(
            name="groq",
            base_url=s.groq_base_url.rstrip("/"),
            api_key=s.groq_api_key,
            models=[m for m in [s.groq_model] if m],
            extra_headers={},
        )
        gemini = _Provider(
            name="gemini",
            base_url=s.gemini_base_url.rstrip("/"),
            api_key=s.gemini_api_key,
            models=[m for m in [s.gemini_model] if m],
            extra_headers={},
        )
        openrouter = _Provider(
            name="openrouter",
            base_url=s.openrouter_base_url.rstrip("/"),
            api_key=s.openrouter_api_key,
            models=[
                m
                for m in [s.openrouter_model, s.openrouter_fallback_model]
                if m
            ],
            extra_headers={
                "HTTP-Referer": s.app_base_url,
                "X-Title": "EstateLens",
            },
            send_reasoning_exclude=True,
        )
        # de-dupe model lists preserving order
        for p in (groq, gemini, openrouter):
            seen: set[str] = set()
            p.models = [m for m in p.models if not (m in seen or seen.add(m))]

        pref = (s.llm_provider or "auto").strip().lower()
        catalog = {"groq": groq, "gemini": gemini, "openrouter": openrouter}
        if pref in catalog:
            chosen = [catalog[pref]]
        else:
            # Prefer Groq / Gemini for free demos; OpenRouter last (daily free cap).
            chosen = [groq, gemini, openrouter]

        return [p for p in chosen if p.api_key and p.models]

    @property
    def primary_model_label(self) -> str:
        providers = self._providers()
        if not providers:
            return self._s.openrouter_model
        p = providers[0]
        return f"{p.name}/{p.models[0]}"

    async def stream_chat(
        self, messages: list[dict], *, max_retries: int = 2
    ) -> AsyncIterator[StreamChunk]:
        providers = self._providers()
        if not providers:
            raise LLMError(
                "provider_unavailable",
                "No LLM API key configured. Set GROQ_API_KEY, GEMINI_API_KEY, "
                "or OPENROUTER_API_KEY in .env.",
            )

        deadline = time.monotonic() + min(70.0, self._s.openrouter_timeout_seconds * 2.5)
        last_error: LLMError | None = None
        for provider in providers:
            for model in provider.models:
                attempt = 0
                while attempt <= max_retries:
                    if time.monotonic() >= deadline:
                        raise last_error or LLMError(
                            "timeout",
                            "Providers took too long. Please retry.",
                        )
                    try:
                        emitted_text = False
                        async for chunk in self._stream_once(provider, model, messages):
                            if chunk.text:
                                emitted_text = True
                            yield chunk
                        if not emitted_text:
                            raise LLMError(
                                "provider_unavailable",
                                f"{provider.name}/{model} returned no visible content.",
                            )
                        return
                    except LLMError as exc:
                        last_error = exc
                        # Already streamed visible tokens — do not concatenate a
                        # second provider's answer into the same turn.
                        if emitted_text:
                            raise
                        log.warning(
                            "llm attempt failed",
                            extra={
                                "provider": provider.name,
                                "model": model,
                                "category": exc.category,
                                "attempt": attempt,
                            },
                        )
                        # Hard quota → next model/provider. Soft rate-limit → backoff
                        # and retry the same endpoint a few times before falling through.
                        if exc.category == "quota_exhausted":
                            break
                        if exc.category == "rate_limited" or "rate limit" in exc.message.lower():
                            attempt += 1
                            if attempt > max_retries:
                                break
                            await asyncio.sleep(min(1.2 * attempt, 4))
                            continue
                        attempt += 1
                        if attempt > max_retries:
                            break
                        await asyncio.sleep(min(2**attempt, 4))
                # next model / provider
            log.warning("llm provider exhausted", extra={"provider": provider.name})

        raise last_error or LLMError("provider_unavailable", "No model produced a response.")

    async def _stream_once(
        self, provider: _Provider, model: str, messages: list[dict]
    ) -> AsyncIterator[StreamChunk]:
        client = httpx.AsyncClient(
            base_url=provider.base_url,
            timeout=httpx.Timeout(self._s.openrouter_timeout_seconds, connect=10.0),
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
                **provider.extra_headers,
            },
        )
        self._clients.append(client)

        # Reasoning models (gpt-oss, o1/o3, deepseek-r1, qwen-*-thinking) will
        # otherwise spend the whole token budget "thinking" and stream no visible
        # answer. Cap thinking low and give the answer more room.
        is_reasoner = any(
            k in model.lower()
            for k in ("gpt-oss", "o1", "o3", "-r1", "reason", "thinking", "think")
        )
        max_out = self._s.openrouter_max_output_tokens
        if is_reasoner:
            max_out = max(max_out, 2048)

        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_out,
            "temperature": 0.2,
        }
        if provider.send_reasoning_exclude:
            payload["reasoning"] = {"exclude": True}
            payload["usage"] = {"include": True}
        if is_reasoner:
            # Groq / OpenAI-compatible knob to keep the hidden reasoning short.
            payload["reasoning_effort"] = "low"

        label = f"{provider.name}/{model}"
        try:
            async with client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise self._classify(resp.status_code, body, provider.name)

                visible = 0
                last_finish: str | None = None
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        raise self._classify(200, json.dumps(obj["error"]), provider.name)
                    choice = (obj.get("choices") or [{}])[0]
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        visible += len(delta)
                        yield StreamChunk(text=delta, model=label)
                    if choice.get("finish_reason"):
                        last_finish = choice["finish_reason"]
                        yield StreamChunk(
                            finish_reason=choice["finish_reason"],
                            usage=obj.get("usage"),
                            model=label,
                        )
                # A reasoning model that burned the budget thinking, or any empty
                # completion: fail so the next provider/model is tried.
                if visible == 0:
                    reason = "spent its budget on hidden reasoning" if last_finish == "length" else "returned no content"
                    raise LLMError("provider_unavailable", f"{label} {reason}.")
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            raise LLMError("timeout", f"{label} timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("provider_unavailable", f"{label} transport error: {exc}") from exc

    @staticmethod
    def _classify(status: int, body: str, provider: str) -> LLMError:
        low = body.lower()
        # Prefer rate-limit over hard quota when both signals appear (common on Groq/Gemini 429s).
        hard_quota = any(
            h in low
            for h in (
                "free-models-per-day",
                "insufficient credits",
                "insufficient_quota",
                "billing",
                "add more credits",
                "payment",
                "tokens per day",
                "tpd",
                "daily limit",
                "daily quota",
                "quota exceeded",
                "exceeded your current quota",
                "resource_exhausted",
            )
        )
        rate_limited = status == 429 or any(h in low for h in _RATE_LIMIT_HINTS)
        if hard_quota and not rate_limited:
            return LLMError(
                "quota_exhausted",
                f"{provider} quota/daily limit reached. Trying another provider if configured.",
            )
        if rate_limited:
            # Gemini often says both "quota" and rate-limits in one 429 — treat as soft limit
            # so we backoff/retry instead of immediately abandoning the provider.
            return LLMError("rate_limited", f"{provider} rate limited.")
        if hard_quota:
            return LLMError(
                "quota_exhausted",
                f"{provider} quota/daily limit reached. Trying another provider if configured.",
            )
        if status in (401, 403):
            return LLMError("provider_unavailable", f"{provider} rejected the API key.")
        if status == 402:
            return LLMError("quota_exhausted", f"{provider} reports no available credit.")
        if 500 <= status < 600 or status == 200:
            return LLMError("provider_unavailable", f"{provider} upstream error: {body[:200]}")
        return LLMError("provider_unavailable", f"{provider} HTTP {status}: {body[:200]}")


# Keep the old name so existing imports keep working.
OpenRouterClient = LLMClient
