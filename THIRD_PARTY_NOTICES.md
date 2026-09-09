# Third-party notices

EstateLens bundles or builds on the following open-source software. Full license
texts are available at each project's repository.

## Reused in this project

### crawl4ai — Apache License 2.0
https://github.com/unclecode/crawl4ai
Used in the local ingestion path (`backend/app/scrapers/browser.py`) for
browser-rendered fetching of challenged public pages. Not included in the
deployed web image. Copyright © the crawl4ai authors.

### Referenced (patterns/UX only — no source copied)
- **assistant-ui** — MIT — https://github.com/assistant-ui/assistant-ui
- **mongodb-developer/GenAI-Showcase** — MIT — https://github.com/mongodb-developer/GenAI-Showcase
- **microsoft/sample-app-aoai-chatGPT** — MIT — https://github.com/microsoft/sample-app-aoai-chatGPT

## Key direct dependencies

### Backend (see `backend/requirements.txt`)
| Package | License |
|---|---|
| FastAPI, Starlette | MIT |
| Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| PyMongo | Apache-2.0 |
| httpx, h11, httpcore | BSD-3-Clause |
| beautifulsoup4 | MIT |
| lxml | BSD-3-Clause |
| typer, click | MIT / BSD-3-Clause |
| tenacity | Apache-2.0 |
| orjson | Apache-2.0 / MIT |
| python-json-logger | BSD-2-Clause |
| nh3 | MIT |
| playwright (ingestion only) | Apache-2.0 |

### Frontend (see `frontend/package.json`)
| Package | License |
|---|---|
| react, react-dom | MIT |
| react-router-dom | MIT |
| vite, @vitejs/plugin-react | MIT |
| tailwindcss, @tailwindcss/vite | MIT |
| lucide-react | ISC |
| react-markdown, remark-gfm, rehype-sanitize | MIT |
| zustand | MIT |
| clsx, tailwind-merge, class-variance-authority | MIT |

Fonts: "Inter" (SIL Open Font License 1.1) is referenced with a system
sans-serif fallback stack.

The DarGlobal and Wasalt names and any collected page content remain the property
of their respective owners. EstateLens is an independent demo and is not
affiliated with, endorsed by, or connected to either company.
