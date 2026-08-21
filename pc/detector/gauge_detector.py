"""Generic template-match-then-read detector: locate a region in a
captured frame by template matching, crop it, and hand the crop to a
reader that turns it into some structured value.

Originally built for HP/MP (locate the bar, OCR "current/max" out of
it) -- replacing an earlier pixel-color-fill heuristic (still visible in
git history) that measured fill percentage from color alone, which was
fast but fragile (MP's fill/empty colors were subtle enough that
lighting/theme changes threw it off). Reading the game's own printed
numbers via OCR is far more reliable.

It turned out to generalize cleanly to other "find a region, read
something out of it" cases -- e.g. pc/detector/chat_reader.py's
DungeonTimeReader scans the chat log for a specific message instead of
a "current/max" pair -- so `reader` just needs a `.read(crop) ->
Optional[T]` method; GaugeDetector doesn't care what T is.

Template matching itself is not cheap (~150ms on a full 1080p-ish
frame), and the target region doesn't move once the game window is up,
so it's only run once per detector and the resulting region is cached --
every later `measure()` call just crops the cached region and reads it.
If reading ever fails on the cached crop (window moved/resized, UI
changed), `measure()` automatically retries once with a fresh
template-match before giving up.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Optional, Protocol, TypeVar

import cv2
import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.template_locator import locate_template

T = TypeVar("T")


class Reader(Protocol[T]):
    def read(self, crop_bgr: np.ndarray) -> Optional[T]: ...


@dataclass
class GaugeDetectionResult(Generic[T]):
    reading: T
    region: Region
    match_score: float


class GaugeDetector(Generic[T]):
    """Detects one region using a template image + a shared reader.

    `reader` (e.g. a GaugeTextReader) is often expensive to construct
    (loads OCR models) -- create one and pass it to every GaugeDetector
    that needs it instead of letting each detector make its own.
    """

    def __init__(self, template_path: Path, reader: "Reader[T]", match_threshold: float = 0.8):
        template_path = Path(template_path)
        self._template = cv2.imread(str(template_path))
        if self._template is None:
            raise FileNotFoundError(f"Could not load template image: {template_path}")
        self._reader = reader
        self._match_threshold = match_threshold
        self._cached_region: Optional[Region] = None
        self._cached_score: float = 0.0

    def relocate(self, frame: np.ndarray) -> Optional[Region]:
        """Force a fresh template match against `frame` and cache the result.

        Normally not needed -- `measure()` locates on first use and
        auto-retries this if a cached region stops working. Call it
        directly if you know the game window moved/resized.
        """
        match = locate_template(frame, self._template, self._match_threshold)
        if match is None:
            self._cached_region = None
            return None
        self._cached_region = match.region
        self._cached_score = match.score
        return match.region

    def measure(self, frame: np.ndarray) -> Optional[GaugeDetectionResult[T]]:
        """Locate (or reuse the cached location of) and read the region in `frame`.

        Returns None if the template couldn't be matched at all (region
        not on screen, covered by another window, UI changed) or the
        reader couldn't parse anything out of the matched crop. Callers
        should treat None as "no new reading this frame", not a zero/empty value.
        """
        region = self._cached_region
        if region is None:
            region = self.relocate(frame)
            if region is None:
                return None

        reading = self._read_region(frame, region)
        if reading is not None:
            return GaugeDetectionResult(reading=reading, region=region, match_score=self._cached_score)

        # Cached region no longer reads cleanly -- the window may have
        # moved/resized. Re-locate once before giving up on this frame.
        region = self.relocate(frame)
        if region is None:
            return None
        reading = self._read_region(frame, region)
        if reading is None:
            return None
        return GaugeDetectionResult(reading=reading, region=region, match_score=self._cached_score)

    def _read_region(self, frame: np.ndarray, region: Region) -> Optional[T]:
        crop = frame[region.top: region.top + region.height, region.left: region.left + region.width]
        return self._reader.read(crop)
