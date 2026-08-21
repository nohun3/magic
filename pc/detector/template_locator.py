"""Locates a UI element (the HP/MP bar) within a captured frame by
template matching against a reference crop, instead of hardcoded pixel
coordinates.

The reference crops live in templates/hp_roi.png and templates/mp_roi.png.
As long as the bar still looks the same, this finds it wherever it is in
the frame -- so unlike a fixed pixel offset, it doesn't need to be
recalibrated just because the window ended up in a different spot.
It does NOT handle the UI being a different *scale* (e.g. a very
different window/resolution) -- that still needs a fresh template crop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from pc.capture.screen_capture import Region


@dataclass
class MatchResult:
    region: Region
    score: float


def locate_template(frame: np.ndarray, template: np.ndarray, threshold: float = 0.8) -> Optional[MatchResult]:
    """Find `template`'s best match location inside `frame`.

    Returns None if the best match score is below `threshold` (bar not
    visible, obscured by another window, UI changed, etc.) so callers
    can decide how to handle a missing reading instead of trusting a
    garbage location.
    """
    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    x, y = max_loc
    h, w = template.shape[:2]
    return MatchResult(region=Region(left=x, top=y, width=w, height=h), score=max_val)
