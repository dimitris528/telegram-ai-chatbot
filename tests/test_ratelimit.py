from bot.ratelimit import SlidingWindowRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_limit_then_blocks_with_retry_hint():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=2, window_seconds=10, clock=clock)
    assert limiter.check("u") == 0
    clock.now = 3
    assert limiter.check("u") == 0
    clock.now = 4
    assert limiter.check("u") == 6  # oldest event (t=0) expires at t=10


def test_window_slides_and_keys_are_independent():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=5, clock=clock)
    assert limiter.check("a") == 0
    assert limiter.check("b") == 0
    assert limiter.check("a") > 0
    clock.now = 5
    assert limiter.check("a") == 0


def test_blocked_attempts_do_not_extend_the_window():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_events=1, window_seconds=5, clock=clock)
    limiter.check("u")
    for t in (1, 2, 3, 4):
        clock.now = t
        assert limiter.check("u") > 0
    clock.now = 5
    assert limiter.check("u") == 0
