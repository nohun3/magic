"""Converts a frame-relative pixel coordinate (as returned by the
detectors -- a position within the captured game-window frame) into the
units Arduino's MOUSE_MOVE command expects.

Handles the DPI-scaling gap documented in README.md's "Known
limitations": screen capture happens in physical pixels, but window
position (win32gui) and monitor size (mss) are reported in whatever
logical/physical mix Windows gives a non-DPI-aware process -- this
derives the scale factor empirically (captured frame size vs. the
window's reported logical size) instead of assuming one.
"""
from __future__ import annotations

from typing import Tuple

import mss

from pc.action.mouse_coords import pixel_to_absolute_mouse
from pc.capture.screen_capture import Region


class FrameToMouseConverter:
    def __init__(self, logical_window_region: Region, frame_shape: Tuple[int, int, int]):
        self.frame_width = frame_shape[1]
        self.frame_height = frame_shape[0]
        self.scale_x = frame_shape[1] / logical_window_region.width
        self.scale_y = frame_shape[0] / logical_window_region.height
        self._window = logical_window_region
        with mss.mss() as sct:
            monitor = sct.monitors[1]
        self._logical_screen_w = monitor["width"] / self.scale_x
        self._logical_screen_h = monitor["height"] / self.scale_y

    def convert(self, frame_x: float, frame_y: float) -> Tuple[int, int]:
        """Frame-relative pixel -> (x, y) units for Arduino's MOUSE_MOVE."""
        logical_x = self._window.left + frame_x / self.scale_x
        logical_y = self._window.top + frame_y / self.scale_y
        return pixel_to_absolute_mouse(
            round(logical_x), round(logical_y), round(self._logical_screen_w), round(self._logical_screen_h)
        )
