"""POST /api/chat — grounded, streaming answers over collected data.

Wire format (SSE, ``text/event-stream``), one event per line-block:

    event: evidence\n data: {...}\n\n   (once, first)
    event: cards\n    data: {...}\n\n   (once, optional)
    event: delta\n    data: {"text": "..."}\n\n   (zero or more)
    event: done\n     data: {...}\n\n   (terminal)
    event: error\n    data: {...}\n\n   (terminal; may replace done)

If inference fails, the evidence and cards are still delivered and the failure is
reported honestly as an ``error`` event — the client keeps DB-backed browsing.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import orjson
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import client_key, enforce_chat_rate_limit, request_id
from app.config import get_settings
from app.models.api import (
    ChatRequest,
    StreamCards,
    StreamDelta,
    StreamDone,
    StreamError,
    StreamEvidence,
)
from app.retrieval.pipeline import retrieve
from app.services.logging import get_logger
import re

from app.services.openrouter import OpenRouterClient, OpenRouterError
from app.services.prompt import (
    build_messages,
    extract_cited_evidence_ids,
    normalize_citations,
    strip_reasoning_preamble,
)

router = APIRouter(tags=["chat"])
log = get_logger("estatelens.chat")

# A citation token that may still be mid-stream at the end of a delta.
_TRAILING_CITE = re.compile(r"[\[\(【]\s*E?\s*\d{0,3}\s*$")


def _sse(model) -> bytes:
    payload = model.model_dump(mode="json")
    return b"event: " + payload["type"].encode() + b"\ndata: " + orjson.dumps(payload) + b"\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, rid: str = Depends(request_id)) -> StreamingResponse:
    settings = get_settings()
    allowed, retry_after = enforce_chat_rate_limit(request)

    history = req.messages[-settings.max_history_messages :]
    history[-1].content = history[-1].content[: settings.max_message_chars]
    user_text = history[-1].content

    async def event_stream() -> AsyncIterator[bytes]:
        t0 = time.monotonic()
        if not allowed:
            yield _sse(
                StreamError(
                    category="rate_limited",
                    message=f"Rate limit reached. Try again in ~{int(retry_after) + 1}s.",
                    request_id=rid,
                )
            )
            return

        try:
            r = await retrieve(
                user_text,
                context_filters=req.context.filters,
                selected_property_ids=req.context.selected_property_ids,
                last_result_ids=req.context.last_result_ids,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("retrieval failed", extra={"request_id": rid})
            yield _sse(StreamError(category="internal", message="Retrieval failed.", request_id=rid))
            return

        t_retrieval = time.monotonic() - t0
        yield _sse(
            StreamEvidence(
                items=r.evidence,
                retrieval_method="structured-filter + mongodb-text-search (lexical)",
                applied_filters=r.applied_filters,
            )
        )
        if r.cards:
            yield _sse(StreamCards(properties=r.cards))

        messages = build_messages(history, r.evidence, r.properties, r.filter_notes)

        or_client = OpenRouterClient(settings)
        answer_parts: list[str] = []
        finish_reason = None
        used_model = None
        usage = None
        pending = ""  # holds a partial citation token straddling two deltas
        # Prelude gate: hold the opening back until we can tell whether a
        # "reasoning" model has leaked an untagged planning monologue. Once the
        # first real content is identified we stop gating and stream normally.
        gate_open = False
        gate_buf = ""
        default_model = or_client.primary_model_label

        def _flush_gate(text: str) -> str:
            cleaned = strip_reasoning_preamble(text)
            return cleaned

        try:
            async for chunk in or_client.stream_chat(messages):
                if chunk.text:
                    answer_parts.append(chunk.text)
                    if not gate_open:
                        gate_buf += chunk.text
                        if len(gate_buf) < 220 and "\n\n" not in gate_buf:
                            continue
                        gate_open = True
                        opening = _flush_gate(gate_buf)
                        buf = pending + opening
                    else:
                        buf = pending + chunk.text
                    # keep a short tail back if it might be an unfinished [E.. / 【E..
                    m = _TRAILING_CITE.search(buf)
                    if m:
                        emit, pending = buf[: m.start()], buf[m.start() :]
                    else:
                        emit, pending = buf, ""
                    if emit:
                        yield _sse(StreamDelta(text=normalize_citations(emit)))
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                    used_model = chunk.model
                    usage = chunk.usage
            if not gate_open and gate_buf:
                # stream ended inside the gate window
                emit = pending + _flush_gate(gate_buf)
                pending = ""
                if emit:
                    yield _sse(StreamDelta(text=normalize_citations(emit)))
        except OpenRouterError as exc:
            log.warning(
                "inference failed",
                extra={"request_id": rid, "category": exc.category},
            )
            yield _sse(StreamError(category=exc.category, message=exc.message, request_id=rid))
            return
        except Exception:  # noqa: BLE001
            log.exception("inference crashed", extra={"request_id": rid})
            yield _sse(StreamError(category="internal", message="Inference error.", request_id=rid))
            return
        finally:
            await or_client.aclose()

        if pending:
            yield _sse(StreamDelta(text=normalize_citations(pending)))

        answer = normalize_citations(strip_reasoning_preamble("".join(answer_parts)))

        # Every provider streamed but nothing usable came back (e.g. a reasoning
        # model that spent its budget thinking). Report it, don't leave a blank
        # bubble.
        if not answer.strip():
            log.warning("empty answer from model", extra={"request_id": rid, "finish_reason": finish_reason})
            yield _sse(
                StreamError(
                    category="provider_unavailable",
                    message="The model returned an empty answer. Please retry.",
                    request_id=rid,
                )
            )
            return

        cited_ids, invalid = extract_cited_evidence_ids(answer, r.evidence)
        if invalid:
            log.warning("model cited unknown evidence", extra={"request_id": rid, "labels": invalid})

        log.info(
            "chat turn",
            extra={
                "request_id": rid,
                "client": client_key(request),
                "retrieval_ms": round(t_retrieval * 1000),
                "total_ms": round((time.monotonic() - t0) * 1000),
                "evidence_count": len(r.evidence),
                "property_count": len(r.properties),
                "answer_chars": len(answer),
                "cited": len(cited_ids),
                "model": used_model or default_model,
                "finish_reason": finish_reason,
            },
        )

        yield _sse(
            StreamDone(
                citations=cited_ids,
                property_ids=[p.id for p in (r.cards or r.properties)],
                model=used_model or default_model,
                finish_reason=finish_reason,
                usage=usage,
                request_id=rid,
            )
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Request-Id": rid,
        },
    )
