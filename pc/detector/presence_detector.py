"""Presence detector: template-match a reference crop against the
captured frame and report whether it's currently visible -- e.g. to
check whether a specific skill/buff icon is showing right now, a toggle
is in a particular state, etc.

Shares GaugeDetector's underlying mechanism (template loaded once from
disk, its on-screen location found via cv2.matchTemplate and then
cached so later calls don't re-search the whole frame every time) but
NOT its "retry on failure" behavior: for HP/MP, not finding the bar is
an error to recover from (the window moved, OCR glitched). Here, "not
present" is frequently the correct, expected answer (a toggle that's
off, a buff that isn't active) -- so a low match score at the cached
spot is trusted as a real "absent" reading, not treated as a reason to
re-search the whole frame. A full re-search only happens if the element
has never been located successfully yet (e.g. it happened to be absent
the very first time this ran).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.template_locator import locate_template


@dataclass
class PresenceResult:
    present: bool
    region: Optional[Region]
    match_score: float


class PresenceDetector:
    def __init__(self, template_path: Path, match_threshold: float = 0.8):
        template_path = Path(template_path)
        self._template = cv2.imread(str(template_path))
        if self._template is None:
            raise FileNotFoundError(f"Could not load template image: {template_path}")
        self._match_threshold = match_threshold
        self._cached_region: Optional[Region] = None

    def relocate(self, frame: np.ndarray) -> Optional[Region]:
        """Force a fresh full-frame search and cache the result (or
        clear the cache if not found this time). Call this directly if
        you know the UI has moved/resized."""
        match = locate_template(frame, self._template, self._match_threshold)
        self._cached_region = match.region if match else None
        return self._cached_region

    def measure(self, frame: np.ndarray) -> PresenceResult:
        region = self._cached_region
        if region is None:
            region = self.relocate(frame)
            if region is None:
                return PresenceResult(present=False, region=None, match_score=0.0)
            # Found it for the first time this call -- re-score at that
            # exact region instead of reporting the bare threshold, so
            # callers see the real match quality here too.

        score = self._score_at(frame, region)
        return PresenceResult(present=score >= self._match_threshold, region=region, match_score=score)

    def _score_at(self, frame: np.ndarray, region: Region) -> float:
        crop = frame[region.top: region.top + region.height, region.left: region.left + region.width]
        if crop.shape[:2] != self._template.shape[:2]:
            return 0.0
        result = cv2.matchTemplate(crop, self._template, cv2.TM_CCOEFF_NORMED)
        return float(result.max())
