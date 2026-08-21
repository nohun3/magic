"""Screen capture module (development step 1).

Captures frames from the game screen using `mss` (fast, no GDI/DirectX
dependency, cross-platform). Frames are returned as BGR numpy arrays so
they can be handed straight to OpenCV without extra conversion in
calling code.

This module only knows how to grab pixels. It has no knowledge of HP/MP,
ROIs, thresholds, or Arduino — that separation is intentional so the
capture layer stays reusable and testable on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import mss
import numpy as np


@dataclass
class Region:
    """A capture region in monitor-local pixel coordinates."""

    left: int
    top: int
    width: int
    height: int

    def to_mss_dict(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


class ScreenCapture:
    """Captures the game screen (or a sub-region of it) as BGR frames.

    Not thread-safe: `mss` requires its capture object to be created and
    used from the same thread. Create one `ScreenCapture` per thread that
    needs to grab frames.

    Three ways to select what gets captured, in priority order:
      1. `window_title` — locate the game window by title (once, at
         construction) and capture its client area. Handles the window
         being in a different spot on screen every run, since the
         position is resolved fresh each time the program starts. The
         window is assumed not to move while the program is running; if
         it does, call `relocate()` to re-resolve it.
      2. `region` — a fixed, explicitly-specified screen region.
      3. `monitor` — a full mss monitor index (fallback/default).
    """

    def __init__(
        self,
        monitor: int = 1,
        region: Optional[Region] = None,
        window_title: Optional[str] = None,
    ):
        self._sct = mss.mss()
        self._monitor_index = monitor
        self._window_title = window_title
        self._region = region

        if window_title is not None:
            self.relocate()

    def relocate(self) -> Region:
        """Re-resolve the target window's bounds by title and cache them.

        Only meaningful when this instance was constructed with
        `window_title`. Call this if the game window has been moved,
        resized, or restarted.
        """
        if self._window_title is None:
            raise ValueError("relocate() requires this ScreenCapture to have been created with window_title")

        # Imported here (not at module top) to avoid a hard dependency on
        # pywin32 for callers who only ever use monitor/region capture.
        from pc.capture.window_locator import locate_window_region

        self._region = locate_window_region(self._window_title)
        return self._region

    @property
    def bounds(self) -> dict:
        """The screen area actually being captured (mss monitor-dict format)."""
        if self._region is not None:
            return self._region.to_mss_dict()
        return self._sct.monitors[self._monitor_index]

    def grab(self) -> np.ndarray:
        """Capture a single frame as a BGR numpy array of shape (H, W, 3)."""
        shot = self._sct.grab(self.bounds)
        frame = np.array(shot)  # BGRA
        return frame[:, :, :3]  # drop alpha channel -> BGR

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
