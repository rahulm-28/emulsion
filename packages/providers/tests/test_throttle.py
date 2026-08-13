"""Throttle and retry, checked against the measured 2-per-11s bucket."""

import pytest
from emulsion_providers import RateLimit, load_manifest
from emulsion_providers.throttle import BACKOFF_SECS, TokenBucket, retry_delay

LIMIT = load_manifest("gpt-image-2").rate_limit


class FakeClock:
    """A monotonic clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_bucket(limit: RateLimit = LIMIT) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    return TokenBucket(limit, monotonic=clock.monotonic), clock


def test_first_requests_up_to_the_limit_do_not_wait():
    bucket, clock = make_bucket()
    for _ in range(LIMIT.requests):
        assert bucket.acquire(clock.sleep) == 0.0
    assert clock.slept == []


def test_the_next_request_waits_out_the_window():
    bucket, clock = make_bucket()
    for _ in range(LIMIT.requests):
        bucket.acquire(clock.sleep)
    waited = bucket.acquire(clock.sleep)
    assert waited == pytest.approx(LIMIT.window_s)


def test_no_wait_once_the_window_has_passed_on_its_own():
    bucket, clock = make_bucket()
    for _ in range(LIMIT.requests):
        bucket.acquire(clock.sleep)
    clock.advance(LIMIT.window_s)
    assert bucket.acquire(clock.sleep) == 0.0


def test_bucket_slides_rather_than_resetting():
    # Two requests at t=0 and t=10 against a 2-per-11s window: the third waits only
    # until the *oldest* ages out (t=11), not for a fresh full window.
    bucket, clock = make_bucket(RateLimit(requests=2, window_s=11))
    bucket.acquire(clock.sleep)
    clock.advance(10)
    bucket.acquire(clock.sleep)
    assert bucket.acquire(clock.sleep) == pytest.approx(1.0)


def test_sustained_rate_matches_the_declared_limit():
    bucket, clock = make_bucket()
    for _ in range(20):
        bucket.acquire(clock.sleep)
    # 20 requests at 2-per-11s should take ~9 windows, not ~20 * 11s.
    expected = (20 - LIMIT.requests) / LIMIT.requests * LIMIT.window_s
    assert clock.now == pytest.approx(expected)


def test_a_limit_of_zero_is_rejected():
    with pytest.raises(ValueError, match="at least one request"):
        TokenBucket(RateLimit(requests=0, window_s=11))


def test_429_escalates_through_the_backoff_table():
    assert [retry_delay(429, i) for i in range(len(BACKOFF_SECS))] == list(BACKOFF_SECS)


def test_429_eventually_gives_up():
    assert retry_delay(429, len(BACKOFF_SECS)) is None


def test_retry_after_header_beats_the_backoff_table():
    # The deployment sent Retry-After: 11 on a real 429. Its number wins over ours.
    assert retry_delay(429, 0, retry_after=11.0) == 11.0


def test_nonsense_retry_after_falls_back_to_the_table():
    assert retry_delay(429, 0, retry_after=-1.0) == BACKOFF_SECS[0]


def test_server_errors_are_retried_exactly_once():
    assert retry_delay(500, 0) == 5.0
    assert retry_delay(500, 1) is None
    assert retry_delay(503, 0) == 5.0


@pytest.mark.parametrize("status", [200, 400, 401, 404])
def test_non_retryable_statuses_stop_immediately(status):
    assert retry_delay(status, 0) is None
