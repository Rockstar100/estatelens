# EstateLens — submission notes

_Independent demo built for the hiring assignment. Not affiliated with DarGlobal
or Wasalt._

## 1. Public URL

- **App:** _pending deployment_ — blocked only on the Atlas `MONGODB_URI` and
  `OPENROUTER_API_KEY` being set in the Render dashboard. All deployable
  artifacts (`Dockerfile`, `render.yaml`, `docker-compose.yml`, lockfiles) are
  complete and the image builds and runs locally.
- **Repository:** _pending_ — `git init` done locally; awaiting a GitHub URL.

## 2. Architecture summary

React + Vite SPA served by a FastAPI backend from a single origin. Public pages
from DarGlobal and Wasalt are collected by a CLI crawler, normalized, and stored
in MongoDB as `properties`, `documents`, `passages`, `crawl_runs`. Chat answers
are produced by a free OpenRouter model constrained to a handful of retrieved
passages; citations are resolved from stored records and validated against the
retrieved set before the response is returned. Retrieval is lexical (structured
MongoDB filters + a text index), documented as such. See
[ARCHITECTURE.md](ARCHITECTURE.md).

## 3. Source coverage & collection dates

_Filled from `python -m scripts.cli coverage` after the ingestion run._

| Source | Pages | Properties (listing / development) | Cities | Latest collection |
|---|---|---|---|---|
| DarGlobal | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| Wasalt | _tbd_ | _tbd_ | _tbd_ | _tbd_ |

Coverage is a point-in-time snapshot, not live inventory, and not a claim of
completeness.

### Known collection limits
- Both sites use anti-bot challenges (Incapsula / Cloudflare). Individual pages
  that stay challenged after a browser render are recorded as `skipped` in
  `crawl_runs`, never fabricated.
- DarGlobal rarely publishes unit-level prices on project pages, so many
  DarGlobal `development` records have `price_amount = null` (shown as
  "Price not listed"), which is faithful to the source.
- Wasalt property-detail data is read from the site's own unauthenticated public
  JSON API (the endpoint the public page calls); expired listings that the API no
  longer serves are skipped with a reason.

## 4. Tested OpenRouter model

- **Primary:** `nvidia/nemotron-3-super-120b-a12b:free`
- **Fallback:** `nex-agi/nex-n2.5-mini:free` (different provider)
- **Tested:** 2026-09-09 — a live streaming generation call against a grounded
  prompt returned a correct, `[E#]`-cited answer in ~4 s. Several other
  advertised `:free` slugs (llama-3.3-70b, deepseek-chat-v3.1, mistral-small,
  qwen3-235b) now 404 with "unavailable for free — use the paid slug", so they
  were rejected. The client only ever calls `:free` routes, never silently falls
  back to a paid model, and surfaces an exhausted account quota as an account
  limit (not retried, not disguised as a model problem).
- **Citation spelling:** the primary model emits fullwidth `【E1】`; the backend
  normalizes `[E1]` / `(E1)` / `【E1】` (including tokens split across stream
  chunks) to the canonical `[E1]` the UI parses.

## 5. Open-source references

See the table in the root [README](../README.md#open-source-references). Reused:
crawl4ai for browser-rendered fetching (ingestion only); MongoDB GenAI-Showcase
and the Microsoft sample as retrieval / citation-UX references; assistant-ui as a
chat-UX reference. Everything else is original to this project.

## 6. Test results

_Filled from `python -m pytest`._

- Unit (pure functions, mocked inference): price/area parsing & missing values,
  allow-listed filter builder, NL→filter extraction, ordinal follow-up
  resolution, citation validation, Wasalt API adapter, idempotent-ingestion
  helpers.
- Integration (local MongoDB, mocked inference): API input validation, property
  list/detail, health/readiness, chat SSE contract incl. the
  inference-unavailable path.
- Eval cases (`tests/eval/cases.json`, 18 cases): DarGlobal & Wasalt factual
  answers, source-specific search, budget/bedroom constraints, sale/rent
  separation, currency & rent-period ambiguity, follow-up references,
  comparisons, missing fields, unsupported locations, empty retrieval,
  conflicting evidence, prompt injection in retrieved text, model failure /
  quota, MongoDB unavailability.
- A small set of real-OpenRouter smoke checks is run manually with the key.

## 7. Known limitations

- Retrieval is keyword + structured filtering, not semantic/vector search.
- The rate limiter is in-memory (single instance); documented in the README.
- Render's free tier cold-starts (~50 s) after idle.
- Conversation history is browser-local only.
- DarGlobal price coverage is thin because the source gates unit pricing.

## 8. Exact local reproduction

See [README → Run it locally](../README.md#run-it-locally). In short:
`docker compose up --build`, then
`python -m scripts.cli create-indexes && python -m scripts.cli scrape --source all --limit 60`.

## 9. For the hiring team

- Original work: backend, both scrapers + normalization, retrieval + filter
  allow-list, OpenRouter client + prompt/citation validation, the whole
  frontend, Docker, tests.
- Reused (with notices preserved): crawl4ai (Apache-2.0) for ingestion-only
  browser rendering; patterns (not code) from the MongoDB and Microsoft samples;
  UX cues from assistant-ui.
- The project is "done" when a reviewer can open the URL, ask grounded questions
  answered from both sources, inspect the supporting citations, browse the
  records, and compare properties.
