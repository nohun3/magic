"""Supervised reader for the fixed-width HP/MP game font.

Unlike general OCR this reader does not detect arbitrary text.  It compares
each character cell with labelled examples captured from the exact game UI.
That makes leading digits real characters instead of something a text
detector is allowed to omit.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from pc.detector.ocr_reader import GaugeReading


CELL_X = 44
CELL_Y = 12
CELL_WIDTH = 10
CELL_HEIGHT = 13
ALPHABET = " 0123456789/"
FIELD_DIGITS = 3
GAUGE_CHARACTER_COUNT = FIELD_DIGITS + 1 + FIELD_DIGITS


def glyph_mask(image_bgr: np.ndarray) -> np.ndarray:
    """Keep the pale pink font fill while rejecting the red gauge bar."""
    b, g, r = cv2.split(image_bgr)
    signed_b = b.astype(np.int16)
    signed_g = g.astype(np.int16)
    signed_r = r.astype(np.int16)
    return (
        (signed_b >= 55)
        & (np.abs(signed_b - signed_g) <= 18)
        & ((signed_r - signed_b) >= 12)
        & ((signed_r - signed_b) <= 90)
        & (signed_r >= 105)
    ).astype(np.uint8)


def extract_cells(image_bgr: np.ndarray, character_count: int) -> list[np.ndarray]:
    mask = glyph_mask(image_bgr)
    cells = []
    for index in range(character_count):
        left = CELL_X + index * CELL_WIDTH
        cell = mask[CELL_Y:CELL_Y + CELL_HEIGHT, left:left + CELL_WIDTH]
        if cell.shape != (CELL_HEIGHT, CELL_WIDTH):
            raise ValueError("gauge ROI is too small for its labelled text")
        cells.append(cell)
    return cells


@dataclass
class FontPrediction:
    reading: GaugeReading
    confidence: float


class GameFontGaugeReader:
    """Nearest-example classifier loaded from a compressed NumPy model."""

    def __init__(self, model_path: Path, minimum_confidence: float = 0.90):
        data = np.load(model_path, allow_pickle=False)
        self.samples = data["samples"].astype(np.uint8)
        self.labels = data["labels"].astype("U1")
        self.minimum_confidence = minimum_confidence

    def _classify(self, cell: np.ndarray) -> tuple[str, float]:
        distances = np.mean(self.samples != cell[None, :, :], axis=(1, 2))
        best = int(np.argmin(distances))
        return str(self.labels[best]), 1.0 - float(distances[best])

    def predict(self, crop_bgr: np.ndarray) -> Optional[FontPrediction]:
        predictions = [
            self._classify(cell)
            for cell in extract_cells(crop_bgr, GAUGE_CHARACTER_COUNT)
        ]
        text = "".join(character for character, _score in predictions)
        if text[FIELD_DIGITS:FIELD_DIGITS + 1] != "/":
            return None
        left, right = (field.strip() for field in text.split("/", 1))
        if not left.isdigit() or not right.isdigit():
            return None
        reading = GaugeReading(int(left), int(right))
        confidence = min(score for _character, score in predictions)
        if reading.maximum <= 0 or reading.current > reading.maximum:
            return None
        return FontPrediction(reading, confidence)
