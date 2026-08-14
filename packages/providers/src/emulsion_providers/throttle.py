"""Rate limiting and retry, driven by what the deployment actually enforces.

The limit is a token bucket — N requests per window — not a per-minute cap. Flattening
it to an RPM figure is what produced the wrong "2 RPM" this project ran on for months;
the real deployment allows 2 requests per 11 seconds, roughly five times that.

Clocks are injected so the tests do not sleep.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from .manifest import RateLimit

# From ../gpt-image-2/generate.py, earned in production: 429 gets three escalating
# retries, a 5xx gets exactly one. A server error that repeats is not a blip.
BACKOFF_SECS: tuple[float, ...] = (5.0, 15.0, 45.0)
SERVER_ERROR_DELAY_SECS = 5.0
MAX_SERVER_ERROR_RETRIES = 1


class TokenBucket:
    """Allows `limit.requests` acquisitions per `limit.window_s`, sliding.

    ponytail: in-process only. Concurrent Container Apps Job executions each get their
    own bucket, so N workers can collectively exceed the deployment limit and rely on
    429 retries to sort it out. That is fine while the worker count is small. When it
    is not, move the timestamps to shared state (Postgres row lock or Redis) behind
    this same `acquire()` signature — callers do not change.
    """

    def __init__(
        self,
        limit: RateLimit,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit.requests < 1:
            raise ValueError(f"rate limit must allow at least one request, got {limit.requests}")
        self._limit = limit
        self._monotonic = monotonic
        self._recent: deque[float] = deque(maxlen=limit.requests)

    def wait_time(self) -> float:
        """Seconds until the next acquisition would be allowed. 0.0 if it is now."""
        if len(self._recent) < self._limit.requests:
            return 0.0
        return max(0.0, self._recent[0] + self._limit.window_s - self._monotonic())

    def acquire(self, sleep: Callable[[float], None] | None = None) -> float:
        """Block until a slot is free, record the use, and return how long we waited.

        `sleep` resolves at call time rather than as a default argument: a default binds
        the function object when the method is defined, which makes it impossible to
        substitute later — including from a test that would rather not wait 11 seconds.
        """
        sleep = sleep or time.sleep
        delay = self.wait_time()
        if delay > 0:
            sleep(delay)
        self._recent.append(self._monotonic())
        return delay


def retry_delay(status: int, attempt: int, retry_after: float | None = None) -> float | None:
    """Seconds to wait before retrying, or None to stop trying.

    `attempt` is 0-based: 0 is the delay before the first retry. `retry_after` is the
    server's own Retry-After header — this deployment sends one on 429, and it is a
    better number than any backoff table we invent.
    """
    if retry_after is not None and retry_after < 0:
        retry_after = None

    if status == 429:
        if attempt >= len(BACKOFF_SECS):
            return None
        return retry_after if retry_after is not None else BACKOFF_SECS[attempt]

    if 500 <= status < 600:
        if attempt >= MAX_SERVER_ERROR_RETRIES:
            return None
        return retry_after if retry_after is not None else SERVER_ERROR_DELAY_SECS

    # 4xx other than 429 is the caller's fault and will fail identically on retry.
    return None
