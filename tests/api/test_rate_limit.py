from __future__ import annotations

from api_app.rate_limit import SlidingWindowRateLimiter


def test_allows_up_to_max_requests_then_blocks():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False


def test_identifiers_are_independent():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is False


def test_window_expiry_frees_up_budget():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=0.05)
    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    import time

    time.sleep(0.1)
    assert limiter.allow("a") is True


def test_reset_clears_all_state():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.allow("a")
    assert limiter.allow("a") is False
    limiter.reset()
    assert limiter.allow("a") is True
