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
from typing import Optional

import cv2
import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.template_locator import locate_template


class SkillPanelLocator:
    def __init__(self, template_path: Path, match_threshold: float = 0.7):
        template_path = Path(template_path)
        self._template = cv2.imread(str(template_path))
        if self._template is None:
            raise FileNotFoundError(f"Could not load template image: {template_path}")
        self._match_threshold = match_threshold
        self._cached_region: Optional[Region] = None

    def relocate(self, frame: np.ndarray) -> Optional[Region]:
        """Force a fresh full-frame search and cache the result. Call
        this if you know the window moved/resized."""
        match = locate_template(frame, self._template, self._match_threshold)
        self._cached_region = match.region if match else None
        return self._cached_region

    def locate(self, frame: np.ndarray) -> Optional[Region]:
        """Return the panel's region, reusing the cached location once
        found. Unlike icon presence, the panel border/background should
        always be on screen while the game is running, so (unlike
        PresenceDetector) this doesn't re-verify on every call."""
        if self._cached_region is None:
            return self.relocate(frame)
        return self._cached_region
