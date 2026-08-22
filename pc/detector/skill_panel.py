"""Locates the skill/quick-slot panel (templates/roi_skill.png) once and
caches it, so icon presence checks can be scoped to search only inside
it instead of the whole captured frame -- faster (smaller area to
matchTemplate against) and avoids any chance of a false match to
something elsewhere on screen that happens to look similar.

The panel's own icons/toggle states change, so matching the *whole*
panel image isn't as clean as HP/MP's bar (score ~0.86 on a live frame
vs. HP/MP's ~1.0) -- match_threshold is set lower accordingly, same
reasoning as the chat log's threshold. This only needs to be "confident
enough that this is the panel", not an exact pixel match.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.template_locator import locate_template


class SkillPanelLocator:
    def __init__(self, template_path: Path, match_threshold: float = 0.7,
                 search_region: Optional[Dict[str, float]] = None):
        template_path = Path(template_path)
        self._template = cv2.imread(str(template_path))
        if self._template is None:
            raise FileNotFoundError(f"Could not load template image: {template_path}")
        self._match_threshold = match_threshold
        self._search_region = search_region
        self._cached_region: Optional[Region] = None

    def relocate(self, frame: np.ndarray) -> Optional[Region]:
        """Force a fresh full-frame search and cache the result. Call
        this if you know the window moved/resized."""
        search_frame = frame
        offset_left = 0
        offset_top = 0
        if self._search_region is not None:
            height, width = frame.shape[:2]
            left = int(width * self._search_region.get("left", 0.0))
            top = int(height * self._search_region.get("top", 0.0))
            right = int(width * self._search_region.get("right", 1.0))
            bottom = int(height * self._search_region.get("bottom", 1.0))
            left = max(0, min(left, width))
            top = max(0, min(top, height))
            right = max(left, min(right, width))
            bottom = max(top, min(bottom, height))
            search_frame = frame[top:bottom, left:right]
            offset_left = left
            offset_top = top

        th, tw = self._template.shape[:2]
        if search_frame.shape[0] < th or search_frame.shape[1] < tw:
            self._cached_region = None
            return None

        match = locate_template(search_frame, self._template, self._match_threshold)
        if match is None:
            self._cached_region = None
        else:
            self._cached_region = Region(
                left=match.region.left + offset_left,
                top=match.region.top + offset_top,
                width=match.region.width,
                height=match.region.height,
            )
        return self._cached_region

    def locate(self, frame: np.ndarray) -> Optional[Region]:
        """Return the panel's region, reusing the cached location once
        found. Unlike icon presence, the panel border/background should
        always be on screen while the game is running, so (unlike
        PresenceDetector) this doesn't re-verify on every call."""
        if self._cached_region is None:
            return self.relocate(frame)
        return self._cached_region
