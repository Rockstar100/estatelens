"""Shared test fixtures. Unit tests mock inference and use pure functions;
integration tests that need MongoDB are marked and skipped when it is absent.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGODB_DATABASE", "estatelens_test")
os.environ.setdefault("OPENROUTER_API_KEY", "")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: needs a running MongoDB")
    config.addinivalue_line("markers", "network: hits a real external service")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
