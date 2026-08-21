"""Loads project-wide runtime settings from pc/config/settings.yaml.

Anything that can change between machines or between games — ROI
coordinates, HP/MP thresholds, capture region, cooldowns, etc. — belongs
in the settings file, not hardcoded in capture/detector/condition code.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "settings.yaml"


def load_settings(path: Optional[Path] = None) -> dict[str, Any]:
    """Load and parse the YAML settings file.

    Args:
        path: Optional override path. Defaults to pc/config/settings.yaml.
    """
    target = path or _DEFAULT_CONFIG_PATH
    with open(target, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
