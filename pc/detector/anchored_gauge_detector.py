"""Reads a gauge (HP/MP) by locating a shared static anchor -- the
dragon skull ornament between the two bars, which never changes
regardless of HP/MP value -- and reading a fixed-offset region from it,
instead of matching the whole bar image directly.

roi_hp.png/roi_mp.png (the whole-bar images) turned out to be unusable
as the *locating* template on their own: they were captured at 100%
fill, and the match score against a partially-filled or near-empty bar
drops enough (simulated as low as ~0.33 at 1% fill) to fail even a
generously low threshold -- exactly when a low-HP/MP reading matters
most. The skull ornament's pixels never change no matter what HP/MP
currently is, so anchoring on it and computing each bar's position via a
fixed offset is fill-percentage-proof by construction (measured 1.0
match score regardless of HP/MP level).

Mirrors GaugeDetector's retry-once-on-read-failure behavior, just
sourced from a WindowContentLocator instead of a direct template match.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from pc.detector.gauge_detector import GaugeDetectionResult, Reader, T
from pc.detector.window_content import WindowContentLocator


class AnchoredGaugeDetector:
    def __init__(self, content_locator: WindowContentLocator, reader: "Reader[T]"):
        self._content_locator = content_locator
        self._reader = reader

    def measure(self, frame: np.ndarray) -> Optional[GaugeDetectionResult[T]]:
        region = self._content_locator.content_region(frame)
        if region is None:
            return None

        reading = self._read_region(frame, region)
        if reading is not None:
            return GaugeDetectionResult(reading=reading, region=region, match_score=1.0)

        # Cached anchor position no longer reads cleanly -- re-locate
        # once before giving up on this frame (mirrors GaugeDetector).
        region = self._content_locator.relocate(frame)
        if region is None:
            return None
        reading = self._read_region(frame, region)
        if reading is None:
            return None
        return GaugeDetectionResult(reading=reading, region=region, match_score=1.0)

    def _read_region(self, frame: np.ndarray, region) -> Optional[T]:
        crop = frame[region.top: region.top + region.height, region.left: region.left + region.width]
        return self._reader.read(crop)
