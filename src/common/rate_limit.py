"""Simple token-bucket rate limiter.

Used to respect arXiv's polite-use minimum of one request every three seconds.
Thread-safe so it can be shared across the retrying wrapper safely.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Ensures at least ``min_interval`` seconds elapse between ``wait()`` calls."""

    def __init__(self, min_interval: float):
        self._min_interval = float(min_interval)
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            to_wait = self._min_interval - elapsed
            if to_wait > 0:
                time.sleep(to_wait)
            self._last_call = time.monotonic()
