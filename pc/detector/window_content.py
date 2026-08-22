"""Locates a popup/panel window by its static border/chrome template,
then exposes a fixed content sub-region relative to that border -- for
windows whose content scrolls/changes (so matching the whole window
image directly is unreliable, see skill_panel.py's docstring) but whose
border/chrome doesn't.

Cropping OCR down to just this content region instead of a generous
guessed rectangle is a real speed win: OCR cost scales with area, and
the guessed 750x620 crop used before this existed was scanning a lot of
either empty space or window chrome that was never going to contain
useful text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.skill_panel import SkillPanelLocator  # generic border locator despite the name


@dataclass
class ContentOffset:
    left: int
    top: int
    width: int
    height: int


class WindowContentLocator:
    def __init__(self, border: SkillPanelLocator, content_offset: ContentOffset):
        self._border = border
        self._offset = content_offset

    def relocate(self, frame: np.ndarray) -> Optional[Region]:
        """Force a fresh border search (bypassing the cache). Call this
        if a caller suspects the cached position has gone stale."""
        self._border.relocate(frame)
        return self.content_region(frame)

    def content_region(self, frame: np.ndarray) -> Optional[Region]:
        border_region = self._border.locate(frame)
        if border_region is None:
            return None
        # Clamp to the frame instead of letting left/top go negative --
        # the border match can land a couple pixels off from run to run,
        # and content_offset.left/top are sometimes calibrated close to
        # 0 (e.g. dialog's -365 practically cancels the anchor's own
        # left position). An unclamped negative left/top silently wraps
        # around in a later frame[top:top+h, left:left+w] slice (Python
        # negative indexing counts from the end of the array) instead of
        # raising, producing an empty crop and a confusing downstream
        # error (e.g. OCR's own resize dividing by a zero width) instead
        # of a clear "off the edge of the frame" signal.
        left = max(0, border_region.left + self._offset.left)
        top = max(0, border_region.top + self._offset.top)
        return Region(
            left=left,
            top=top,
            width=self._offset.width,
            height=self._offset.height,
        )

    def crop_content(self, frame: np.ndarray) -> Optional[np.ndarray]:
        region = self.content_region(frame)
        if region is None:
            return None
        return frame[region.top: region.top + region.height, region.left: region.left + region.width]
