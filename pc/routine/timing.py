"""Shared timing helpers for the 1-4 step routine."""
from __future__ import annotations

import random
import time


DEFAULT_JITTER_SECONDS = 0.010


def sleep_jittered(seconds: float, jitter_seconds: float = DEFAULT_JITTER_SECONDS) -> None:
    """Sleep for the requested interval with uniform +/- timing jitter."""
    delay = float(seconds) + random.uniform(-jitter_seconds, jitter_seconds)
    time.sleep(max(0.0, delay))
