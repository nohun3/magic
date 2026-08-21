"""Manual test for development Step 4: HP/MP condition judgment.

Usage (run from the project root, with the venv active):

    python -m pc.condition.test_condition

Polls HP/MP continuously and prints each reading. When a condition
fires (HP/MP at or below its configured threshold, and its cooldown has
elapsed), it prints a `[TRIGGER ...]` marker instead of actually
sending a key -- Arduino output doesn't exist yet (Step 5+), so this
step only proves the trigger logic (threshold + cooldown, HP/MP
independent) is correct.

To verify cooldown behavior: let HP sit below its threshold and confirm
`hp_low` only re-fires every `cooldown_seconds`, not every poll. To
verify independence: trigger HP and MP at different times and confirm
one's cooldown never delays the other.

Ctrl+C to stop.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.capture.screen_capture import Region, ScreenCapture  # noqa: E402
from pc.capture.window_locator import WindowNotFoundError  # noqa: E402
from pc.detector.hpmp import build_hp_mp_detectors  # noqa: E402
from pc.detector.ocr_reader import GaugeTextReader  # noqa: E402
from pc.condition.condition import Condition  # noqa: E402
from pc.condition.condition_manager import ConditionManager  # noqa: E402


def _build_capture(settings: dict) -> ScreenCapture:
    cap_cfg = settings["capture"]
    if cap_cfg.get("window_title"):
        return ScreenCapture(window_title=cap_cfg["window_title"])
    region = Region(**cap_cfg["region"]) if cap_cfg.get("region") else None
    return ScreenCapture(monitor=cap_cfg.get("monitor", 1), region=region)


def _build_condition_manager(settings: dict) -> ConditionManager:
    cond_cfg = settings["conditions"]
    conditions = [
        Condition(
            name=name,
            threshold_percent=cfg["threshold_percent"],
            cooldown_seconds=cfg["cooldown_seconds"],
        )
        for name, cfg in cond_cfg.items()
    ]
    keys = {name: cfg["key"] for name, cfg in cond_cfg.items()}
    return ConditionManager(conditions, keys)


def main() -> None:
    settings = load_settings()
    print("Loading OCR model...")
    reader = GaugeTextReader()
    hp_detector, mp_detector = build_hp_mp_detectors(settings, _PROJECT_ROOT, reader)
    manager = _build_condition_manager(settings)

    try:
        with _build_capture(settings) as cap:
            print("Polling HP/MP. Ctrl+C to stop.\n")
            while True:
                frame = cap.grab()
                hp_result = hp_detector.measure(frame)
                mp_result = mp_detector.measure(frame)

                hp_pct = hp_result.reading.percent if hp_result else None
                mp_pct = mp_result.reading.percent if mp_result else None

                fired = manager.evaluate({"hp_low": hp_pct, "mp_low": mp_pct})

                hp_str = f"{hp_pct:5.1f}%" if hp_pct is not None else " N/A "
                mp_str = f"{mp_pct:5.1f}%" if mp_pct is not None else " N/A "
                line = f"HP={hp_str}  MP={mp_str}"
                for action in fired:
                    line += f"   [TRIGGER {action.condition_name} -> key {action.key}]"
                print(line)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
