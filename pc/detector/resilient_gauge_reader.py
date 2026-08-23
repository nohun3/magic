"""Resilient wrapper around GaugeTextReader for one specific gauge (HP or
MP): remembers the last successfully-read `max` value and uses it to
recover from a specific, observed OCR failure mode -- misreading the "/"
between current and max as a stray digit (real example seen in testing:
"MP:45/414" OCR'd back as "MP:451414", the "/" read as "1"). The normal
"current/max" regex still handles everything else; this only kicks in
when that fails.

One instance of this per gauge (HP gets its own, MP gets its own) even
though they can share the same underlying GaugeTextReader/OCR engine --
the max-value memory has to be per-gauge, not shared.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from pc.detector.ocr_reader import GaugeReading, GaugeTextReader
from pc.detector.game_font_reader import GameFontGaugeReader

_VALUE_PATTERN = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")


class ResilientGaugeReader:
    def __init__(self, reader: GaugeTextReader, gauge_name: str,
                 suspicious_output_dir: Path):
        self._reader = reader
        self._gauge_name = gauge_name.lower()
        self._suspicious_output_dir = suspicious_output_dir / self._gauge_name
        self._last_known_max: Optional[int] = None
        self._last_known_current: Optional[int] = None
        self._last_saved_signature = None
        model_name = (
            "gauge_font_model.npz" if self._gauge_name == "hp"
            else "mp_gauge_font_model.npz"
        )
        model_path = suspicious_output_dir.parent / model_name
        self._font_reader = (
            GameFontGaugeReader(model_path, minimum_confidence=0.94)
            if model_path.exists()
            else None
        )

    def read(self, crop_bgr: np.ndarray) -> Optional[GaugeReading]:
        if self._font_reader is not None:
            prediction = self._font_reader.predict(crop_bgr)
            if (
                prediction is not None
                and prediction.confidence >= self._font_reader.minimum_confidence
            ):
                reading = prediction.reading
                self._record_large_change(crop_bgr, reading, "game-font-model")
                self._last_known_max = reading.maximum
                self._last_known_current = reading.current
                return reading

        combined = " ".join(self._reader.read_lines(crop_bgr))

        match = _VALUE_PATTERN.search(combined)
        if match:
            reading = GaugeReading(current=int(match.group(1)), maximum=int(match.group(2)))
            if reading.maximum <= 0 or reading.current > reading.maximum:
                self._save_suspicious(crop_bgr, "invalid", reading, combined)
                return None
            self._record_large_change(crop_bgr, reading, combined)
            self._last_known_max = reading.maximum
            self._last_known_current = reading.current
            return reading

        reading = self._recover(combined)
        if reading is not None:
            self._save_suspicious(crop_bgr, "recovered", reading, combined)
        else:
            self._save_suspicious(crop_bgr, "unreadable", None, combined)
        return reading

    def _record_large_change(self, crop_bgr: np.ndarray, reading: GaugeReading,
                             raw_text: str) -> None:
        if self._last_known_max is not None and reading.maximum != self._last_known_max:
            self._save_suspicious(crop_bgr, "max_changed", reading, raw_text)
            return
        if self._last_known_current is None:
            return
        reference_max = self._last_known_max or reading.maximum
        if abs(reading.current - self._last_known_current) >= reference_max * 0.25:
            self._save_suspicious(crop_bgr, "large_change", reading, raw_text)

    def _save_suspicious(self, crop_bgr: np.ndarray, reason: str,
                         reading: Optional[GaugeReading], raw_text: str) -> None:
        """Save a raw gauge crop once per distinct suspicious transition."""
        current = reading.current if reading is not None else -1
        maximum = reading.maximum if reading is not None else -1
        signature = (reason, self._last_known_current, self._last_known_max,
                     current, maximum, raw_text)
        if signature == self._last_saved_signature:
            return
        self._last_saved_signature = signature
        try:
            self._suspicious_output_dir.mkdir(parents=True, exist_ok=True)
            timestamp_ms = int(time.time() * 1000)
            previous = self._last_known_current if self._last_known_current is not None else "na"
            path = self._suspicious_output_dir / (
                f"{timestamp_ms}_{reason}_prev{previous}_ocr{current}_max{maximum}.png"
            )
            cv2.imwrite(str(path), crop_bgr)
        except (OSError, cv2.error):
            pass

    def _recover(self, text: str) -> Optional[GaugeReading]:
        """Anchor on the last known max to salvage a reading the normal
        regex couldn't parse. Only ever returns a value that's <= the
        known max, so a bogus recovery can't silently look "healthy"."""
        if self._last_known_max is None:
            return None

        max_str = str(self._last_known_max)
        idx = text.find(max_str)
        if idx <= 0:
            return None  # max not present, or nothing precedes it to be "current"

        prefix_digits = re.sub(r"\D", "", text[:idx])  # digits only, drop any OCR noise
        if not prefix_digits:
            return None

        # "MP:39/447" can become "MP:391447" when OCR reads the slash
        # as "1". That leaves two valid candidates: 391 (raw prefix) and
        # 39 (drop the suspected separator). Do not blindly prefer the
        # raw candidate -- that caused live readings such as
        # 53 -> 391 -> 251 -> 11 instead of 53 -> 39 -> 25 -> 11.
        candidates = []
        for candidate_text in (prefix_digits, prefix_digits[:-1]):
            if not candidate_text:
                continue
            candidate = int(candidate_text)
            if candidate <= self._last_known_max and candidate not in candidates:
                candidates.append(candidate)

        if not candidates or self._last_known_current is None:
            # Without a previous clean reading there is no safe way to
            # distinguish a real three-digit current from current + a
            # slash misread as "1". Dropping this tick is safer than
            # manufacturing a plausible but dangerously wrong value.
            return None

        current = min(candidates, key=lambda value: abs(value - self._last_known_current))
        self._last_known_current = current
        return GaugeReading(current=current, maximum=self._last_known_max)
