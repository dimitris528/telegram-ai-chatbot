"""In-process per-user rate limiting."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Hashable


class SlidingWindowRateLimiter:
    """Allow at most ``max_events`` per ``window_seconds`` for each key.

    State lives in memory, which is appropriate for a single bot process.
    Scaling to multiple replicas would require a shared store such as Redis.
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[Hashable, deque[float]] = {}

    def check(self, key: Hashable) -> float:
        """Record an event for ``key`` if allowed.

        Returns ``0.0`` when the event is allowed, otherwise the number of
        seconds until the caller may try again (the event is not recorded).
        """
        now = self._clock()
        events = self._events.setdefault(key, deque())
        while events and now - events[0] >= self.window_seconds:
            events.popleft()

        if len(events) >= self.max_events:
            return self.window_seconds - (now - events[0])

        events.append(now)
        return 0.0
