"""A single shared, pooled MongoDB client.

Uses ``pymongo.AsyncMongoClient`` (the current supported PyMongo async client) so
request handlers never block the event loop on a database round-trip. The client
is created once at startup and closed at shutdown.
"""

from __future__ import annotations

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings, get_settings

_client: AsyncMongoClient | None = None


async def connect(settings: Settings | None = None) -> AsyncMongoClient:
    global _client
    if _client is None:
        settings = settings or get_settings()
        _client = AsyncMongoClient(
            settings.mongodb_uri,
            maxPoolSize=settings.mongodb_max_pool_size,
            serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
            connectTimeoutMS=settings.mongodb_timeout_ms,
            socketTimeoutMS=settings.mongodb_timeout_ms * 3,
            tz_aware=True,
            appname="estatelens",
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
