"""HP detection: locate the shared HP/MP anchor (the dragon skull, see
templates/roi_hpmp_anchor.png) and OCR the "HP:current/max" text out of
a fixed offset region from it. See anchored_gauge_detector.py for why
this doesn't match the HP bar image directly.
"""
from __future__ import annotations

from pc.detector.anchored_gauge_detector import AnchoredGaugeDetector
from pc.detector.ocr_reader import GaugeTextReader
from pc.detector.resilient_gauge_reader import ResilientGaugeReader
from pc.detector.skill_panel import SkillPanelLocator
from pc.detector.window_content import ContentOffset, WindowContentLocator


def build_hp_detector(anchor: SkillPanelLocator, content_offset: ContentOffset, reader: GaugeTextReader) -> AnchoredGaugeDetector:
    content_locator = WindowContentLocator(anchor, content_offset)
    # ResilientGaugeReader wraps the shared OCR engine with its own
    # last-known-max memory (HP's max shouldn't be mixed up with MP's) --
    # see resilient_gauge_reader.py for why.
    return AnchoredGaugeDetector(content_locator, ResilientGaugeReader(reader))
