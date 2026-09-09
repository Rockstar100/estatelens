"""In-memory sliding-window rate limiter.

Single-instance only: limits are per-process and reset on restart. This is
acceptable for a single-container demo and is documented as a limitation in the
README. Swap for a shared store (Redis) before running multiple replicas.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float = 60.0) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_events:
                retry_after = self.window - (now - q[0])
                return False, max(retry_after, 0.0)
            q.append(now)
            return True, 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
