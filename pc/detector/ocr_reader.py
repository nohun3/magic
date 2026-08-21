"""Reads "LABEL:current/max" style text (e.g. "HP:190/190") off a
cropped gauge-bar image using PaddleOCR.

`GaugeTextReader` also exposes the underlying line-by-line OCR via
`read_lines()`, for callers that need something other than a
"current/max" pair out of a crop -- e.g. pc/detector/chat_reader.py
scans multi-line chat log text for a specific message instead. Building
one shared GaugeTextReader and passing it to both keeps there being only
one (expensive-to-load) OCR model in memory.

Model loading takes a few seconds and OCR inference is much slower than
the old pixel-color heuristic (tens of ms per call, not sub-ms) -- build
one GaugeTextReader and reuse it across frames rather than constructing
a new one per read. This also means detection should be polled at its
own (lower) rate rather than tied to the capture FPS; that's handled in
the condition/scheduling layer, not here.

Uses the "mobile" PP-OCRv5 detection/recognition models rather than the
default "medium" ones -- roughly 3x faster (~180ms vs ~600ms per call)
with no accuracy loss observed on this UI's clean, high-contrast digits.

Note: `enable_mkldnn=False` works around a PaddlePaddle 3.x + oneDNN
inference bug on this machine (text detection raised
`NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support`
with mkldnn enabled). If a future paddlepaddle release fixes that, this
can be removed to regain the mkldnn speedup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from paddleocr import PaddleOCR

_VALUE_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)")


@dataclass
class GaugeReading:
    current: int
    maximum: int

    @property
    def percent(self) -> float:
        if self.maximum <= 0:
            return 0.0
        return max(0.0, min(100.0, self.current / self.maximum * 100.0))


class GaugeTextReader:
    def __init__(self):
        self._ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            enable_mkldnn=False,
        )

    def read_lines(self, crop_bgr: np.ndarray) -> List[str]:
        """OCR `crop_bgr` and return the recognized text, one entry per
        detected line (in whatever order PaddleOCR found them -- not
        guaranteed to be top-to-bottom). Empty list if nothing was
        recognized."""
        results = self._ocr.predict(crop_bgr)
        if not results:
            return []
        return results[0].get("rec_texts") or []

    def read(self, crop_bgr: np.ndarray) -> Optional[GaugeReading]:
        """OCR `crop_bgr` and parse the first "current/max" pair found.

        Returns None if no text was recognized or nothing matched the
        expected "number/number" pattern (bar obscured, OCR misfire, etc.).
        """
        combined = " ".join(self.read_lines(crop_bgr))
        match = _VALUE_PATTERN.search(combined)
        if not match:
            return None
        return GaugeReading(current=int(match.group(1)), maximum=int(match.group(2)))
