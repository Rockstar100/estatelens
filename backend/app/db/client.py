"""A single shared, pooled MongoDB client.

Uses ``pymongo.AsyncMongoClient`` (the current supported PyMongo async client) so
request handlers never block the event loop on a database round-trip. The client
is created once at startup and closed at shutdown.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings, get_settings
from app.services.logging import get_logger

_client: AsyncMongoClient | None = None
_log = get_logger("estatelens.mongo")


def mongo_host(uri: str | None = None) -> str:
    """Hostname only (no user/password) so we can log which cluster is in use."""
    raw = (uri or get_settings().mongodb_uri).strip()
    tail = raw.split("@")[-1]
    return tail.split("/")[0].split("?")[0] or "unknown"

# Split a mongodb[+srv] URI into scheme, userinfo (greedy, up to the LAST '@'
# before the host) and the host/params tail.
_URI_RE = re.compile(r"^(mongodb(?:\+srv)?://)(.+)@([^@]+)$", re.IGNORECASE)


def normalize_mongo_uri(uri: str) -> str:
    """Percent-encode the username/password if they contain reserved characters
    (a raw ``@`` or ``:`` in a pasted password otherwise makes the URI
    unparseable). Already-encoded credentials are left untouched."""
    m = _URI_RE.match(uri.strip())
    if not m:
        return uri
    scheme, userinfo, rest = m.groups()
    if "%" in userinfo:  # assume already encoded
        return uri
    user, sep, pwd = userinfo.partition(":")
    enc_user = quote_plus(user)
    enc = enc_user + (":" + quote_plus(pwd) if sep else "")
    return f"{scheme}{enc}@{rest}"


async def connect(settings: Settings | None = None) -> AsyncMongoClient:
    global _client
    if _client is None:
        settings = settings or get_settings()
        _client = AsyncMongoClient(
            normalize_mongo_uri(settings.mongodb_uri),
            maxPoolSize=settings.mongodb_max_pool_size,
            serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
            connectTimeoutMS=settings.mongodb_timeout_ms,
            socketTimeoutMS=settings.mongodb_timeout_ms * 3,
            tz_aware=True,
            appname="estatelens",
        )
        _log.info(
            "mongo client opened",
            extra={"host": mongo_host(settings.mongodb_uri), "database": settings.mongodb_database},
        )
    return _client


async def disconnect() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def get_client() -> AsyncMongoClient:
    if _client is None:
        raise RuntimeError("Mongo client not initialised; call connect() first.")
    return _client


def get_db() -> AsyncDatabase:
    return get_client()[get_settings().mongodb_database]


async def ping() -> None:
    """Raises if the server is unreachable."""
    await get_client().admin.command("ping")
