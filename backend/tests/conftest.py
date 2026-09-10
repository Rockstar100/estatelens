"""Shared test fixtures.

Safety: several integration tests call ``delete_many`` to set up a known state.
To make it impossible for that to ever touch a real database, this file FORCES
``MONGODB_DATABASE`` to a dedicated test name (overriding any value inherited
from the shell or a ``.env`` file), and ``require_test_db()`` asserts the name
looks like a test DB before any destructive fixture runs.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
# FORCE (not setdefault): a leaked MONGODB_DATABASE=estatelens must not win.
os.environ["MONGODB_DATABASE"] = "estatelens_pytest"
# FORCE every LLM provider key empty: the suite mocks inference, and a real key
# in .env must not make tests hit a live provider (env vars beat the .env file).
for _k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"):
    os.environ[_k] = ""
os.environ.setdefault("LLM_PROVIDER", "auto")

_ALLOWED_TEST_DBS = {"estatelens_pytest"}


def require_test_db() -> str:
    name = os.environ.get("MONGODB_DATABASE", "")
    if name not in _ALLOWED_TEST_DBS and not name.endswith(("_test", "_pytest")):
        raise RuntimeError(
            f"refusing to run a destructive test against database {name!r}; "
            "expected a *_test / *_pytest database"
        )
    return name


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: needs a running MongoDB")
    config.addinivalue_line("markers", "network: hits a real external service")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
