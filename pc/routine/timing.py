"""Shared timing helpers for the 1-4 step routine."""
from __future__ import annotations

import random
import time


DEFAULT_JITTER_SECONDS = 0.010
SHORT_KEY_HOLD_MIN_MS = 50
SHORT_KEY_HOLD_MAX_MS = 80


def sleep_jittered(seconds: float, jitter_seconds: float = DEFAULT_JITTER_SECONDS) -> None:
    """Sleep for the requested interval with uniform +/- timing jitter."""
    delay = float(seconds) + random.uniform(-jitter_seconds, jitter_seconds)
    time.sleep(max(0.0, delay))


def send_random_key_tap(link, key: str) -> tuple[bool, int]:
    """Send one ordinary key tap held for a random 50-80ms."""
    hold_ms = random.randint(SHORT_KEY_HOLD_MIN_MS, SHORT_KEY_HOLD_MAX_MS)
    ack = link.send_and_wait("KEY", f"{key} {hold_ms}")
    return ack is not None and ack.ok, hold_ms


def sleep_transition_randomized(min_seconds: float = 0.5,
                                max_seconds: float = 1.0) -> float:
    """Sleep for a uniformly random transition delay and return it."""
    delay = random.uniform(min_seconds, max_seconds)
    sleep_jittered(delay, jitter_seconds=0.0)
    return delay
