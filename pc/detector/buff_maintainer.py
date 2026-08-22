"""If a buff (e.g. meditation) isn't currently active, find its skill
icon and report where to double-click to reactivate it.

Doesn't send the click itself -- returns the click target region so the
caller decides how to dispatch it (through the action queue, directly
via SerialLink, etc.), consistent with the rest of pc/detector/ only
ever reading screen state, never controlling input itself.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from pc.capture.screen_capture import Region


@dataclass
class BuffCheckResult:
    needs_reactivation: bool
    skill_icon_region: Optional[Region]  # where to click, if needs_reactivation


class BuffMaintainer:
    def __init__(self, buff_detector, skill_icon_detector, cooldown_seconds: float):
        """
        Args:
            buff_detector: a presence detector (see presence_detector.py /
                any_presence_detector.py / scoped_icon_detector.py -- any
                of them expose `.measure(frame) -> PresenceResult`) for
                the buff icon, scoped to roi_buff.
            skill_icon_detector: same shape, for the skill bar icon that
                (re)activates the buff, scoped to roi_skill.
            cooldown_seconds: don't re-trigger more often than this, even
                if the buff stays missing across many checks (e.g. while
                its cast is on cooldown) -- avoids spamming clicks.
        """
        self._buff_detector = buff_detector
        self._skill_icon_detector = skill_icon_detector
        self._cooldown = cooldown_seconds
        self._last_trigger: Optional[float] = None

    def check(self, frame: np.ndarray) -> BuffCheckResult:
        buff_result = self._buff_detector.measure(frame)
        if buff_result.present:
            return BuffCheckResult(needs_reactivation=False, skill_icon_region=None)

        now = time.monotonic()
        if self._last_trigger is not None and (now - self._last_trigger) < self._cooldown:
            return BuffCheckResult(needs_reactivation=False, skill_icon_region=None)

        icon_result = self._skill_icon_detector.measure(frame)
        if not icon_result.present:
            # Buff is missing but we can't find its skill icon either
            # (obscured, different action bar page, etc.) -- nothing
            # sensible to click, so don't trigger and don't start the
            # cooldown (retry again next check instead of waiting it out).
            return BuffCheckResult(needs_reactivation=False, skill_icon_region=None)

        self._last_trigger = now
        return BuffCheckResult(needs_reactivation=True, skill_icon_region=icon_result.region)
