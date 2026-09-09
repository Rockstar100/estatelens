# syntax=docker/dockerfile:1

# ---------- Stage 1: build the React frontend ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: Python runtime (API + static SPA) ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Runtime deps only — no browser, no ingestion extras.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/

# Built SPA is served by FastAPI from backend/static.
COPY --from=frontend /app/frontend/dist ./backend/static

# Non-root runtime user.
RUN useradd --system --uid 10001 --home /app appuser \
    && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
url='http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health'; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status==200 else 1)"

# Bind to 0.0.0.0 and honour the host-provided PORT.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
