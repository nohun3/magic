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
from typing import Optional

import numpy as np

from pc.detector.ocr_reader import GaugeReading, GaugeTextReader

_VALUE_PATTERN = re.compile(r"(\d+)\s*/\s*(\d+)")  # kept in sync with ocr_reader.py's pattern


class ResilientGaugeReader:
    def __init__(self, reader: GaugeTextReader):
        self._reader = reader
        self._last_known_max: Optional[int] = None

    def read(self, crop_bgr: np.ndarray) -> Optional[GaugeReading]:
        combined = " ".join(self._reader.read_lines(crop_bgr))

        match = _VALUE_PATTERN.search(combined)
        if match:
            reading = GaugeReading(current=int(match.group(1)), maximum=int(match.group(2)))
            self._last_known_max = reading.maximum
            return reading

        return self._recover(combined)

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

        # Try the prefix as-is first (covers "nothing actually went
        # wrong here, the regex just didn't match for some other
        # reason"), then with one trailing character dropped (the
        # suspected misread "/").
        for candidate in (prefix_digits, prefix_digits[:-1]):
            if not candidate:
                continue
            current = int(candidate)
            if current <= self._last_known_max:
                return GaugeReading(current=current, maximum=self._last_known_max)
        return None
