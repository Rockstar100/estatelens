# Architecture

## Overview

```
                     ┌──────────────────────────── one Docker image ───────────────────────────┐
  Browser  ────────► │  FastAPI (app.main)                                                     │
   (SPA)             │    ├─ GET  /                → built React SPA (backend/static)           │
                     │    ├─ POST /api/chat       → SSE: evidence → cards → delta* → done|error │
                     │    ├─ GET  /api/properties → allow-listed filter → MongoDB               │
                     │    ├─ GET  /api/properties/{id}                                          │
                     │    ├─ GET  /api/sources    → coverage computed from collections         │
                     │    └─ GET  /api/health, /api/readiness                                   │
                     │            │                     │                                      │
                     │            ▼                     ▼                                      │
                     │   retrieval pipeline      OpenRouter client (free routes only)          │
                     │   (structured + text)                                                   │
                     └────────────┬───────────────────────────────────────────────────────────┘
                                  ▼
                         MongoDB (Atlas in prod)
                   properties · documents · passages · crawl_runs
                                  ▲
                                  │  idempotent upserts + JSONL snapshot
                     ┌────────────┴───────────────┐
                     │  CLI crawler (ingestion)   │   ← never run by the web app
                     │  scripts/cli.py            │
                     │    DarGlobal adapter  ─────┼──► Playwright render → JSON-LD + facts strip
                     │    Wasalt adapter     ─────┼──► api.wasalt.com JSON (PDPs) + Playwright (info pages)
                     └────────────────────────────┘
```

## Request flow: `POST /api/chat`

1. **Validate & bound** — last message must be from the user; history is trimmed
   to `MAX_HISTORY_MESSAGES`, the latest message to `MAX_MESSAGE_CHARS`. A
   per-IP in-memory sliding-window limiter guards the endpoint.
2. **Retrieve** (`app/retrieval/pipeline.py`):
   - deterministic NL→filter extraction merged with any explicit context filters;
   - ordinal references ("the first and third") resolved against the ids last
     shown;
   - structured MongoDB query for matching property records (exact numeric
     rules: unknown price never satisfies a budget; currencies/rent-periods kept
     apart);
   - MongoDB **text-index** search over `passages` (keyword, not semantic);
   - top-K (~6) passages assembled, each with resolved URL / title /
     collection date / passage id.
3. **Stream** an `evidence` event, then a `cards` event (DB records verbatim).
4. **Generate** one call to the OpenRouter model with a system prompt that
   forbids inventing facts, forbids emitting URLs, and requires `[E#]` citations
   from the supplied set. `delta` events stream the text.
5. **Validate citations** — every `[E#]` in the answer is checked against the
   retrieved evidence set; unknown labels are logged. A `done` event carries the
   validated citation ids and the model actually used.
6. **On inference failure** — a single `error` event with a category
   (`provider_unavailable` / `quota_exhausted` / `timeout` / `rate_limited` /
   `internal`). Evidence and cards were already delivered, so DB-backed browsing
   continues; no fake answer is shown. Quota exhaustion is never retried and is
   labelled as an account limit.

## Data model

| Collection | Purpose | Key fields | Identity |
|---|---|---|---|
| `properties` | normalized listing / development records | see `app/models/property.py`; money as `Decimal128`, missing → `null` | `id` unique; `(source, source_record_id)` unique where present |
| `documents` | one cleaned public page | `cleaned_text`, `content_hash`, `extraction_method/status` | `(source, canonical_url)` unique |
| `passages` | retrievable chunks | `text`, `page_title`, `section_heading`, `property_id?`, `active` | `id` unique; text index on text+title+heading |
| `crawl_runs` | per-run bookkeeping | `attempted/succeeded/skipped/failed`, `coverage_summary` | `id` unique |

**Idempotency:** writes are upserts keyed by stable id + `content_hash`. When a
document's hash changes, its old passages are marked `active=False` and fresh
ones inserted — no orphan active chunks. A failed crawl never deletes prior good
data.

## Retrieval method (stated plainly)

Structured MongoDB filtering over `properties` + a MongoDB **text index** over
`passages`. This is **lexical** retrieval. There is no vector/embedding search.
Filters are built only from an allow-list of fields and operators
(`app/retrieval/filters.py`); model output, if ever used for extraction, is
parsed into a typed Pydantic schema first — model-generated queries are never
executed.

## Security

- Inputs and ids validated; request size, history length and pagination bounded.
- MongoDB filters from allow-listed fields/operators only.
- In-memory rate limiter (single-instance; noted as a limitation).
- Markdown is sanitized (`rehype-sanitize`) and only `http(s)` links render.
- Ingestion is unreachable from the public UI.
- Secrets stay in the environment — never in Docker layers, logs, snapshots, or
  the browser bundle. Logs carry request id, stage timings, result counts, model
  id and an error category — never secrets or full conversation content.
- Conversation history is browser-local only.

## Deployment

Multi-stage `Dockerfile`: Node stage builds the SPA; `python:3.12-slim` runtime
installs `backend/requirements.txt`, copies the backend and the built assets to
`backend/static`, runs as a non-root user, binds `0.0.0.0:$PORT`, and defines a
`HEALTHCHECK` against `/api/health`. `render.yaml` runs this as a single free
Docker web service against MongoDB Atlas. The browser/ingestion dependencies
(`requirements-ingest.txt`, Playwright) are deliberately excluded from the image.
