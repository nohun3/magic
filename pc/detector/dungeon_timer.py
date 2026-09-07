"""Detect the blue on-screen dungeon countdown without using the EXP bar."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from pc.capture.screen_capture import Region


_TIME_PATTERN = re.compile(r"(?<!\d)(\d{1,2}):([0-5]\d):([0-5]\d)(?!\d)")


@dataclass(frozen=True)
class DungeonTimerReading:
    hours: int
    minutes: int
    seconds: int
    region: Region

    @property
    def total_seconds(self) -> int:
        return self.hours * 3600 + self.minutes * 60 + self.seconds

    @property
    def text(self) -> str:
        return f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}"


class DungeonTimerDetector:
    """Find cyan text-line candidates in a small relative search region."""

    def __init__(self, reader, config: dict):
        self._reader = reader
        self._search = config.get(
            "search_region",
            {"left": 0.0, "top": 0.60, "right": 0.25, "bottom": 1.0},
        )
        self._hsv_lower = tuple(config.get("hsv_lower", [80, 60, 80]))
        self._hsv_upper = tuple(config.get("hsv_upper", [130, 255, 255]))
        self._min_width = int(config.get("min_width", 55))
        self._max_width = int(config.get("max_width", 180))
        self._min_height = int(config.get("min_height", 10))
        self._max_height = int(config.get("max_height", 40))
        self.last_reading: Optional[DungeonTimerReading] = None

    @property
    def last_text(self) -> Optional[str]:
        return self.last_reading.text if self.last_reading is not None else None

    def measure(self, frame: np.ndarray) -> Optional[DungeonTimerReading]:
        height, width = frame.shape[:2]
        left = max(0, min(width, int(width * float(self._search.get("left", 0.0)))))
        top = max(0, min(height, int(height * float(self._search.get("top", 0.60)))))
        right = max(left, min(width, int(width * float(self._search.get("right", 0.25)))))
        bottom = max(top, min(height, int(height * float(self._search.get("bottom", 1.0)))))
        search_crop = frame[top:bottom, left:right]
        if search_crop.size == 0:
            return None

        hsv = cv2.cvtColor(search_crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.asarray(self._hsv_lower, dtype=np.uint8),
            np.asarray(self._hsv_upper, dtype=np.uint8),
        )
        grouped = cv2.dilate(
            mask, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3)), iterations=1
        )
        contours = cv2.findContours(
            grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )[0]
        candidates = []
        for contour in contours:
            x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
            if not self._min_width <= candidate_width <= self._max_width:
                continue
            if not self._min_height <= candidate_height <= self._max_height:
                continue
            candidates.append((x, y, candidate_width, candidate_height))

        for x, y, candidate_width, candidate_height in sorted(
            candidates, key=lambda box: (box[1], box[0])
        ):
            x1, y1 = max(0, x - 4), max(0, y - 4)
            x2 = min(search_crop.shape[1], x + candidate_width + 4)
            y2 = min(search_crop.shape[0], y + candidate_height + 4)
            crop = search_crop[y1:y2, x1:x2]
            for line in self._reader.read_lines(crop):
                match = _TIME_PATTERN.search(re.sub(r"\s+", "", line))
                if match is None:
                    continue
                hours, minutes, seconds = (int(value) for value in match.groups())
                reading = DungeonTimerReading(
                    hours=hours,
                    minutes=minutes,
                    seconds=seconds,
                    region=Region(
                        left=left + x1,
                        top=top + y1,
                        width=x2 - x1,
                        height=y2 - y1,
                    ),
                )
                self.last_reading = reading
                return reading
        return None
