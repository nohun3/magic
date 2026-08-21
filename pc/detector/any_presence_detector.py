"""Detects presence via any of several template variants of the same
icon -- e.g. an item icon that renders differently depending on
context/state (like hotel_return_icon looking different in the
inventory grid vs. the quick-slot bar, or before/after being clicked).
"Present" if ANY variant currently matches.

This is different from a pair like ats_on/ats_off: those are two
mutually-exclusive PresenceDetectors representing two different real
states you want to tell apart. This is for one logical thing ("is the
hotel key available") that just happens to be drawn more than one way.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import numpy as np

from pc.detector.presence_detector import PresenceDetector, PresenceResult

if TYPE_CHECKING:
    from pc.detector.scoped_icon_detector import ScopedIconDetector
    from pc.detector.skill_panel import SkillPanelLocator


class AnyPresenceDetector:
    def __init__(self, template_paths: List[Path], match_threshold: float = 0.8):
        if not template_paths:
            raise ValueError("AnyPresenceDetector needs at least one template path")
        self._detectors = [PresenceDetector(p, match_threshold) for p in template_paths]

    def measure(self, frame: np.ndarray) -> PresenceResult:
        best: Optional[PresenceResult] = None
        for detector in self._detectors:
            result = detector.measure(frame)
            if result.present:
                return result
            if best is None or result.match_score > best.match_score:
                best = result
        return best


def build_icon_detector(
    icon_cfg: Dict[str, Any], project_root: Path, panel: Optional[SkillPanelLocator] = None
) -> Union[PresenceDetector, AnyPresenceDetector, "ScopedIconDetector"]:
    """Build the right detector type from an `icons.<name>` config entry.

    Supports a single `template:` (-> PresenceDetector) or a list under
    `templates:` (-> AnyPresenceDetector, "present" if any one matches)
    for icons that render differently in different contexts/states.

    Pass `panel` (a SkillPanelLocator) to scope the search to inside the
    skill panel instead of the whole frame -- see scoped_icon_detector.py.
    """
    threshold = icon_cfg.get("match_threshold", 0.8)
    detector: Union[PresenceDetector, AnyPresenceDetector]
    if "templates" in icon_cfg:
        paths = [project_root / t for t in icon_cfg["templates"]]
        detector = AnyPresenceDetector(paths, threshold)
    else:
        detector = PresenceDetector(project_root / icon_cfg["template"], threshold)

    if panel is not None:
        from pc.detector.scoped_icon_detector import ScopedIconDetector  # local import: avoids a circular import (scoped_icon_detector imports this module)

        return ScopedIconDetector(panel, detector)
    return detector
