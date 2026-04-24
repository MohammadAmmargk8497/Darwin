"""Unit tests for src.common.rate_limit."""

from __future__ import annotations

import time

from src.common.rate_limit import RateLimiter


def test_first_call_is_immediate():
    limiter = RateLimiter(min_interval=1.0)
    t0 = time.monotonic()
    limiter.wait()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1


def test_second_call_enforces_interval():
    limiter = RateLimiter(min_interval=0.2)
    limiter.wait()
    t0 = time.monotonic()
    limiter.wait()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.18  # small fudge for timing precision


def test_spaced_calls_do_not_wait():
    limiter = RateLimiter(min_interval=0.1)
    limiter.wait()
    time.sleep(0.15)
    t0 = time.monotonic()
    limiter.wait()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05
