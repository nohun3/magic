"""Wraps an icon presence detector (PresenceDetector or
AnyPresenceDetector) so it only searches within the skill panel (see
skill_panel.py) instead of the whole captured frame.
"""
from __future__ import annotations

from typing import Union

import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.any_presence_detector import AnyPresenceDetector
from pc.detector.presence_detector import PresenceDetector, PresenceResult
from pc.detector.skill_panel import SkillPanelLocator

IconDetector = Union[PresenceDetector, AnyPresenceDetector]


class ScopedIconDetector:
    def __init__(self, panel: SkillPanelLocator, icon_detector: IconDetector):
        self._panel = panel
        self._icon_detector = icon_detector

    def measure(self, frame: np.ndarray) -> PresenceResult:
        panel_region = self._panel.locate(frame)
        if panel_region is None:
            return PresenceResult(present=False, region=None, match_score=0.0)

        crop = frame[
            panel_region.top: panel_region.top + panel_region.height,
            panel_region.left: panel_region.left + panel_region.width,
        ]
        result = self._icon_detector.measure(crop)
        if result.region is None:
            return result

        # The icon detector's region is relative to the panel crop --
        # offset it back to full-frame coordinates so callers (e.g. the
        # mouse-move test) don't need to know this was scoped at all.
        offset_region = Region(
            left=result.region.left + panel_region.left,
            top=result.region.top + panel_region.top,
            width=result.region.width,
            height=result.region.height,
        )
        return PresenceResult(present=result.present, region=offset_region, match_score=result.match_score)
