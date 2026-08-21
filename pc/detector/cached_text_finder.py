"""Caches OCR results for a window's content region across calls, and
only re-runs OCR (~4s) when the region's pixels have actually changed
(e.g. the list scrolled or its content changed) -- useful for a caller
that checks/re-checks the same still-open window more than once in a
short span (e.g. verifying a click landed, or polling for text to
appear) instead of paying the OCR cost every single time.

Cache invalidation is exact-pixel-equality on the content crop, not a
time-based expiry: cheap to compute (a numpy array comparison over a
few hundred KB is sub-millisecond) and exactly correct -- no risk of
serving a stale read past some arbitrary TTL, and no risk of paying for
OCR again when nothing actually changed.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.chat_reader import KoreanTextReader, find_text_region
from pc.detector.window_content import WindowContentLocator


class CachedTextFinder:
    def __init__(self, content_locator: WindowContentLocator, reader: KoreanTextReader):
        self._content_locator = content_locator
        self._reader = reader
        self._cached_crop: Optional[np.ndarray] = None
        self._cached_lines: List[Tuple[str, Region]] = []

    def read_lines(self, frame: np.ndarray) -> List[Tuple[str, Region]]:
        """Return (text, box) pairs for the window's current content,
        reusing the last OCR pass if the content crop is pixel-identical
        to last time (list hasn't scrolled/changed)."""
        crop = self._content_locator.crop_content(frame)
        if crop is None:
            return []

        if self._cached_crop is not None and crop.shape == self._cached_crop.shape and np.array_equal(crop, self._cached_crop):
            return self._cached_lines

        lines = self._reader.read_lines_with_boxes(crop)
        self._cached_crop = crop
        self._cached_lines = lines
        return lines

    def find(self, frame: np.ndarray, *needles: str) -> Tuple[Optional[Region], List[Tuple[str, Region]]]:
        """Returns (content-local region of the first line matching all
        `needles`, or None; the full list of lines seen, for diagnostics)."""
        lines = self.read_lines(frame)
        return find_text_region(lines, *needles), lines
