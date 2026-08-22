"""Blanks out everything in a crop except pixels of a given color --
for OCR targets where the text we actually want is a distinct,
consistent color from the surrounding dialog content (e.g. a dialog's
yellow "action" text vs. its plain-white lore/body paragraph).

Why this helps: PaddleOCR's detection pass finds every text-shaped
region in the image, then recognition runs on each one -- both scale
with how much text is in the crop, not just the part a caller actually
wants. Blanking the irrelevant text removes it from detection entirely,
so there's nothing for the detector to find there and nothing for
recognition to spend time reading. Measured ~10x faster (7810ms ->
805ms) on a real post-gate confirm dialog crop in
pc/routine/step_move_to_wasteland.py, which also happened to fix an OCR
misrecognition of the target line (see that module) -- likely because
the recognizer no longer has nearby unrelated glyphs to get confused by.

Only safe to use where the target text's color is both consistent and
NOT shared by other text nearby in the same crop -- check this per
dialog before relying on it (a screenshot + a quick color histogram is
enough, see the conversation this was built in).
"""
from __future__ import annotations

import numpy as np
import cv2

# Measured against real yellow "action" text (e.g. "버림받은 자들의
# 땅", "발을 내딛는다") in the post-gate confirm dialogs -- see
# pc/routine/step_move_to_wasteland.py. Loose enough to survive
# anti-aliased edge pixels without pulling in the dialog's white body
# text (which sits near hue ~0, saturation ~0).
YELLOW_HSV_LOW = (15, 80, 120)
YELLOW_HSV_HIGH = (40, 255, 255)


def mask_non_yellow(crop: np.ndarray) -> np.ndarray:
    """Returns a same-size BGR image with every pixel outside the yellow
    HSV range above replaced with black."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, YELLOW_HSV_LOW, YELLOW_HSV_HIGH)
    masked = np.zeros_like(crop)
    masked[mask > 0] = crop[mask > 0]
    return masked
