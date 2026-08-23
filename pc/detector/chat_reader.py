"""Reads the dungeon-entry remaining-time message out of the chat log
area (see templates/roi_chatting.png).

Unlike the HP/MP gauge text (always exactly one "current/max" line of
digits/Latin characters), the chat log is mostly Korean and scrolls
through many unrelated system/chat messages at once. Two consequences:

- It needs its own OCR model. GaugeTextReader's English/digit-tuned
  "PP-OCRv5_mobile_rec" model reads garbage on Hangul ('******', mangled
  characters) -- confirmed by testing against this exact chat crop.
  KoreanTextReader here uses "korean_PP-OCRv5_mobile_rec" instead, which
  reads it correctly. That means chat reading needs a second OCR model
  loaded alongside GaugeTextReader's, not a shared one.
- Instead of assuming there's one line of interesting text, this scans
  every OCR'd line for the specific "던전 시간 N분 남았습니다" pattern
  and returns the first match. No match is a normal outcome (the
  message isn't always on screen), not a failure.

Also notably slower than HP/MP: OCR-ing the whole chat panel (~800x190px,
several lines of text) takes ~4s per call vs. HP/MP's ~180ms for a tiny
digit strip -- fine given dungeon time only needs checking every so
often, not every frame.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

import numpy as np
from paddleocr import PaddleOCR

from pc.capture.screen_capture import Region

_DUNGEON_TIME_PATTERN = re.compile(r"던전\s*시간\s*(\d+)\s*분\s*남았습니다")


# Match the first duration in messages such as
# "dungeon time is 147 minutes remaining (account balance: 147 minutes)".
# Unicode escapes keep the Korean pattern stable across terminal code pages.
_DUNGEON_TIME_PATTERN = re.compile(
    r"\ub358\uc804\s*\uc2dc\uac04\uc774?\s*(\d+)\s*\ubd84\s*\ub0a8\uc558\uc2b5\ub2c8\ub2e4"
)


@dataclass
class DungeonTimeReading:
    minutes_remaining: int


class KoreanTextReader:
    """Same shape as GaugeTextReader (own PaddleOCR instance, `read_lines()`),
    but with a Korean-capable recognition model instead of the
    English/digit-tuned one used for HP/MP."""

    def __init__(self):
        self._ocr = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
            # Default (960) resizes the detection input larger than our
            # crops need -- 480 measured ~28% faster with no text lost,
            # just some adjacent lines merging differently (e.g. "허수아비
            # 수련장" as one line instead of two). Only risk: two unrelated
            # bits of text merging onto the same line could make a
            # multi-needle find_text_region() search match something it
            # shouldn't -- acceptable so far, revisit if that ever happens.
            text_det_limit_side_len=480,
            enable_mkldnn=False,
        )

    def read_lines(self, crop_bgr: np.ndarray) -> List[str]:
        results = self._ocr.predict(crop_bgr)
        if not results:
            return []
        return results[0].get("rec_texts") or []

    def read_lines_with_boxes(self, crop_bgr: np.ndarray) -> List[Tuple[str, Region]]:
        """Like read_lines(), but paired with each line's bounding box
        (in crop-local pixel coordinates) -- for when a caller needs to
        know *where* a piece of text is, not just what it says (e.g. to
        click on it)."""
        results = self._ocr.predict(crop_bgr)
        if not results:
            return []
        r = results[0]
        texts = r.get("rec_texts") or []
        boxes = r.get("rec_boxes")
        if boxes is None or len(boxes) != len(texts):
            return []
        out = []
        for text, box in zip(texts, boxes):
            x1, y1, x2, y2 = (int(v) for v in box)
            out.append((text, Region(left=x1, top=y1, width=x2 - x1, height=y2 - y1)))
        return out


def needles_match_fn(*needles: str) -> Callable[[str], bool]:
    """Same whitespace-insensitive substring-containment test
    find_text_region() uses, as a standalone predicate -- for callers
    that need to run it against one line at a time instead of a whole
    lines_with_boxes list (see pc/detector/remembered_text.py)."""
    compact_needles = [re.sub(r"\s+", "", needle) for needle in needles]
    return lambda text: all(needle in re.sub(r"\s+", "", text) for needle in compact_needles)


def exact_match_fn(target: str) -> Callable[[str], bool]:
    """Whitespace-insensitive *exact* match instead of substring
    containment -- for text that has a sibling entry a substring search
    would ambiguously also match (e.g. "버림받은 자들의 땅" vs "버림받은
    자들의 땅: 심연", see step_move_to_wasteland.py)."""
    compact_target = re.sub(r"\s+", "", target)
    return lambda text: re.sub(r"\s+", "", text) == compact_target


def find_text_region(lines_with_boxes: List[Tuple[str, Region]], *needles: str) -> Optional[Region]:
    """Return the bounding box of the first line containing every string
    in `needles` (e.g. find_text_region(lines, "오렌", "여관")), or None
    if no line matches. Whitespace in the OCR'd text is ignored so a
    stray/missing space doesn't break the match."""
    match_fn = needles_match_fn(*needles)
    for text, region in lines_with_boxes:
        if match_fn(text):
            return region
    return None


class DungeonTimeReader:
    def __init__(self, reader: KoreanTextReader):
        self._reader = reader

    def read(self, crop_bgr: np.ndarray) -> Optional[DungeonTimeReading]:
        for line in self._reader.read_lines(crop_bgr):
            match = _DUNGEON_TIME_PATTERN.search(line)
            if match:
                return DungeonTimeReading(minutes_remaining=int(match.group(1)))
        return None


def extract_dungeon_minutes(lines: List[str]) -> Optional[int]:
    """Return the first dungeon duration in OCR lines, or None."""
    for line in lines:
        match = _DUNGEON_TIME_PATTERN.search(line)
        if match:
            return int(match.group(1))
    return None
