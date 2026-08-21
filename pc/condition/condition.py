"""Threshold-based condition with cooldown-gated triggering.

A condition is "true" when the gauge's current value is at or below a
percentage threshold. While it stays true (e.g. HP pinned under 30%
during a long fight), it doesn't fire on every single poll -- only once
every `cooldown_seconds` -- so a held-down low-HP state doesn't flood
the action queue with the same key over and over.

Cooldown (not edge-detection) is used deliberately: if we only fired on
the transition into "low", HP dropping further while still under the
threshold would never trigger another heal. Cooldown keeps retriggering
at a safe rate for as long as the condition holds.

Uses `time.monotonic()` and is polled, never sleeps -- callers decide
how often to call `check()`; this class doesn't block anything.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Condition:
    name: str
    threshold_percent: float
    cooldown_seconds: float
    _last_trigger_time: Optional[float] = field(default=None, init=False, repr=False)

    def check(self, current_percent: Optional[float]) -> bool:
        """Return True if this condition should fire right now.

        `current_percent` is the latest gauge reading (0-100), or None
        if no reading was available this poll (detector didn't find the
        bar / OCR failed) -- treated as "don't trigger", not as 0%, so a
        transient detection glitch can't cause a false trigger.
        """
        if current_percent is None:
            return False
        if current_percent > self.threshold_percent:
            return False

        now = time.monotonic()
        if self._last_trigger_time is not None and (now - self._last_trigger_time) < self.cooldown_seconds:
            return False

        self._last_trigger_time = now
        return True

    def reset(self) -> None:
        """Clear the cooldown timer, e.g. after a macro stop/restart."""
        self._last_trigger_time = None
