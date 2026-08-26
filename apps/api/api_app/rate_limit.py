"""A minimal in-memory sliding-window rate limiter (spec §19: "Rate limiting" on the
magic-link request endpoint). Sufficient for a single-process deployment; a
multi-instance production deployment would need this backed by Redis (`redis_url` in
`packages/config` exists for exactly this, unused today) so all instances share one
counter. Deliberately per-identifier (caller passes an email or an IP, or both) rather
than global.
"""

from __future__ import annotations

import time
from collections import defaultdict


class SlidingWindowRateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, identifier: str) -> bool:
        """Records a hit and returns whether it was within budget. Always records the
        attempt (even a rejected one still occupies a slot) so a caller can't dodge
        the limiter by hammering it — matching how real fixed-budget rate limiters
        behave."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        hits = self._hits[identifier]
        while hits and hits[0] < cutoff:
            hits.pop(0)
        allowed = len(hits) < self._max_requests
        hits.append(now)
        return allowed

    def reset(self) -> None:
        self._hits.clear()
