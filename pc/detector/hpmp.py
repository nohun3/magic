"""Convenience factory: build both the HP and MP detectors (sharing one
hpmp_anchor position cache and one OCR reader) from settings.yaml in one
call, since every caller (pc/main.py, the various test scripts) needs
the exact same wiring.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from pc.detector.anchored_gauge_detector import AnchoredGaugeDetector
from pc.detector.hp_detector import build_hp_detector
from pc.detector.mp_detector import build_mp_detector
from pc.detector.ocr_reader import GaugeTextReader
from pc.detector.skill_panel import SkillPanelLocator
from pc.detector.window_content import ContentOffset


def build_hp_mp_detectors(
    settings: Dict[str, Any], project_root: Path, reader: GaugeTextReader
) -> Tuple[AnchoredGaugeDetector, AnchoredGaugeDetector]:
    anchor_cfg = settings["hpmp_anchor"]
    # Shared: it's the exact same physical skull position for both bars,
    # so only one of them ever has to pay for the actual matchTemplate
    # search -- the other just reuses the cached position.
    hpmp_anchor = SkillPanelLocator(project_root / anchor_cfg["template"], anchor_cfg.get("match_threshold", 0.9))

    hp_detector = build_hp_detector(hpmp_anchor, ContentOffset(**settings["hp"]["content_offset"]), reader)
    mp_detector = build_mp_detector(hpmp_anchor, ContentOffset(**settings["mp"]["content_offset"]), reader)
    return hp_detector, mp_detector
