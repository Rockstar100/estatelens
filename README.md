# EstateLens

Grounded AI property research over **public pages from [DarGlobal](https://darglobal.co.uk) and [Wasalt](https://wasalt.sa)**.

Ask in chat — answers come only from scraped MongoDB records, with `[E#]` citations back to stored pages. Explore, compare, and inspect coverage on the same origin.

> Independent demo. Not affiliated with DarGlobal or Wasalt.

**Repo:** [github.com/Rockstar100/estatelens](https://github.com/Rockstar100/estatelens)

---

## Features

| Surface | What it does |
|---|---|
| **Chat** | SSE streaming answers from Groq / Gemini / OpenRouter, grounded in retrieved passages + property records |
| **Explore** | Filter collected listings (source, city, sale/rent, type, bedrooms, budget) |
| **Compare** | Up to 3 records side-by-side; flags incomparable price bases |
| **Sources** | Live coverage counts, collection dates, retrieval method, active model |

---

## Architecture

```
Browser (React + Vite)
        │  one origin
        ▼
FastAPI ──► MongoDB (properties · documents · passages · crawl_runs)
   │
   └──► LLM (Groq → Gemini → OpenRouter) ──► cited SSE answer

CLI crawler (local only) ──► DarGlobal + Wasalt ──► normalize ──► MongoDB + JSONL
```

- **One Docker image** serves the SPA and `/api/*`.
- **Retrieval:** structured Mongo filters + MongoDB text search over passages (optional Gemini embeddings when configured).
- **Ingestion is CLI-only** — never started by chat or on boot.
- **No server-side chat history** — conversations live in the browser `localStorage`.

### Layout

```
frontend/          React + TypeScript + Vite + Tailwind
backend/
  app/main.py      FastAPI (API + static SPA)
  app/api/         chat (SSE), properties, sources, health
  app/retrieval/   NLU filters, keyword (+ optional semantic) search
  app/services/    multi-provider LLM client, prompts, embeddings
  app/scrapers/    DarGlobal + Wasalt adapters
  scripts/cli.py   scrape · validate · import/export · indexes · embed
docs/              ARCHITECTURE.md · SUBMISSION.md
data/snapshots/    JSONL snapshots (gitignored except .gitkeep)
```

---

## Quick start

**Prerequisites:** Docker, Node 20+, Python 3.12+, and at least one free LLM key
([Groq](https://console.groq.com/keys), [Gemini](https://aistudio.google.com/apikey),
or [OpenRouter](https://openrouter.ai/keys)).

```bash
git clone https://github.com/Rockstar100/estatelens.git
cd estatelens
cp .env.example .env
# Edit .env — set GROQ_API_KEY and/or GEMINI_API_KEY and/or OPENROUTER_API_KEY
# Set MONGODB_URI to your Atlas SRV string (the app uses this, not local Docker Mongo)
```

### Docker (API → Atlas)

```bash
docker compose up --build
# → http://localhost:8000  (reads MONGODB_URI from .env)
```

Local Mongo is **off** by default. Only start it if you explicitly want a disk copy:

```bash
docker compose --profile local-mongo up -d mongo
```

### Dev (hot reload)

```bash
# Terminal 1 — API (uses Atlas from .env; no local Mongo required)
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2 — SPA (proxies /api → :8000)
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

Import a snapshot (or scrape) before chatting so Mongo has data:

```bash
cd backend
python -m scripts.cli create-indexes
python -m scripts.cli import-snapshot ../data/snapshots/full-YYYYMMDD.jsonl
# or: python -m scripts.cli scrape --source all --limit 60
```

---

## Environment

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `auto` (default: Groq → Gemini → OpenRouter) or `groq` / `gemini` / `openrouter` |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq OpenAI-compatible chat (default `openai/gpt-oss-20b`) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Gemini chat + optional embeddings |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` / `OPENROUTER_FALLBACK_MODEL` | Free `:free` routes |
| `MONGODB_URI` / `MONGODB_DATABASE` | Mongo connection |
| `APP_BASE_URL` | Public origin (CORS / referer) |
| `SEMANTIC_RETRIEVAL` | `true` to blend Gemini passage embeddings when indexed |
| `PORT` / `LOG_LEVEL` | Listen port and log level |

Never commit `.env`. Only `.env.example` is tracked.

---

## Ingestion (CLI)

Both sites use JS challenges. The crawler renders public pages with a real browser (Crawl4AI / Playwright) the way a visitor would — it does **not** solve CAPTCHAs.

```bash
cd backend
pip install -r requirements-ingest.txt
python -m playwright install --with-deps chromium

python -m scripts.cli create-indexes
python -m scripts.cli scrape --source all --limit 60
python -m scripts.cli coverage
python -m scripts.cli validate
python -m scripts.cli export-snapshot --out ../data/snapshots/full-$(date +%Y%m%d).jsonl

# Optional semantic layer (needs GEMINI_API_KEY)
python -m scripts.cli embed
```

| Source | Discovery | Extraction |
|---|---|---|
| **DarGlobal** | `sitemap.xml` → project / info pages | Browser HTML → JSON-LD + key facts |
| **Wasalt** | CDN sitemaps → listing URLs | Public JSON API for PDPs + browser for info pages |

---

## Tests

```bash
cd backend
python -m pytest                       # needs local Mongo for integration
python -m pytest -m "not integration"  # unit only

cd ../frontend
npm run build                          # typecheck + production build
```

---

## Production image

```bash
docker build -t estatelens .
docker run --rm -p 8000:8000 \
  -e MONGODB_URI="<atlas-uri>" \
  -e MONGODB_DATABASE=estatelens \
  -e GROQ_API_KEY="<key>" \
  -e LLM_PROVIDER=auto \
  -e APP_BASE_URL="https://your.host" \
  estatelens
```

`render.yaml` targets a single free Render web service + MongoDB Atlas. Set secrets in the host dashboard (`sync: false`).

---

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — request flow, collections, security notes  
- [docs/SUBMISSION.md](docs/SUBMISSION.md) — assignment checklist, coverage, test notes  
