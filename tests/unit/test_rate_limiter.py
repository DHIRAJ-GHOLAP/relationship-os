"""Unit tests for sliding-window rate limiting logic."""

import time
import pytest
from apps.api.src.core.middleware import InMemoryRateLimiter


def test_rate_limiter_allows_under_threshold():
    limiter = InMemoryRateLimiter()
    key = "test_ip_1"
    for _ in range(5):
        limited, _ = limiter.is_rate_limited(key, max_requests=5, window_seconds=60)
        assert limited is False


def test_rate_limiter_blocks_above_threshold():
    limiter = InMemoryRateLimiter()
    key = "test_ip_2"
    for _ in range(5):
        limiter.is_rate_limited(key, max_requests=5, window_seconds=60)

    # 6th request should be blocked
    limited, retry_after = limiter.is_rate_limited(key, max_requests=5, window_seconds=60)
    assert limited is True
    assert retry_after > 0


def test_rate_limiter_isolates_keys():
    limiter = InMemoryRateLimiter()
    for _ in range(5):
        limiter.is_rate_limited("user_a", max_requests=5, window_seconds=60)

    # user_b should not be blocked
    limited, _ = limiter.is_rate_limited("user_b", max_requests=5, window_seconds=60)
    assert limited is False
