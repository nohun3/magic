"""Manual test for icon presence detection (PresenceDetector).

Usage (run from the project root, with the venv active):

    python -m pc.detector.test_presence single <icon_name>   # one check, saves debug overlay
    python -m pc.detector.test_presence live <icon_name>      # continuous checks, 'q' to quit

<icon_name> must match a key under `icons:` in pc/config/settings.yaml
(e.g. "hotel_return_icon"). Defaults to "hotel_return_icon" if omitted.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.capture.screen_capture import Region, ScreenCapture  # noqa: E402
from pc.capture.window_locator import WindowNotFoundError  # noqa: E402
from pc.detector.any_presence_detector import build_icon_detector  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402

OUTPUT_DIR = _PROJECT_ROOT / "output"


def _build_capture(settings: dict) -> ScreenCapture:
    cap_cfg = settings["capture"]
    if cap_cfg.get("window_title"):
        return ScreenCapture(window_title=cap_cfg["window_title"])
    region = Region(**cap_cfg["region"]) if cap_cfg.get("region") else None
    return ScreenCapture(monitor=cap_cfg.get("monitor", 1), region=region)


def _build_panel(settings: dict) -> SkillPanelLocator:
    panel_cfg = settings["skill_roi"]
    return SkillPanelLocator(_PROJECT_ROOT / panel_cfg["template"], panel_cfg.get("match_threshold", 0.7))


def _build_detector(settings: dict, icon_name: str, panel: SkillPanelLocator):
    icon_cfg = settings["icons"].get(icon_name)
    if icon_cfg is None:
        available = ", ".join(sorted(settings.get("icons", {})))
        raise SystemExit(f"Unknown icon {icon_name!r} in settings.yaml (available: {available})")
    return build_icon_detector(icon_cfg, _PROJECT_ROOT, panel=panel)


def _draw_result(frame, label: str, result, color) -> None:
    if result.region is not None:
        top_left = (result.region.left, result.region.top)
        bottom_right = (result.region.left + result.region.width, result.region.top + result.region.height)
        cv2.rectangle(frame, top_left, bottom_right, color, 2)
        y = result.region.top - 8
    else:
        y = 30
    text = f"{label}: {'PRESENT' if result.present else 'absent'} (score={result.match_score:.3f})"
    cv2.putText(frame, text, (10, max(y, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def single_check(icon_name: str) -> None:
    settings = load_settings()
    panel = _build_panel(settings)
    detector = _build_detector(settings, icon_name, panel)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with _build_capture(settings) as cap:
        frame = cap.grab()

    result = detector.measure(frame)
    print(f"{icon_name}: present={result.present} score={result.match_score:.3f} region={result.region}")

    debug = frame.copy()
    _draw_result(debug, icon_name, result, (0, 255, 0) if result.present else (0, 0, 255))
    out_path = OUTPUT_DIR / f"presence_test_{icon_name}.png"
    cv2.imwrite(str(out_path), debug)
    print(f"Debug overlay saved -> {out_path}")


def live_check(icon_name: str) -> None:
    settings = load_settings()
    panel = _build_panel(settings)
    detector = _build_detector(settings, icon_name, panel)

    with _build_capture(settings) as cap:
        print(f"Live presence check for {icon_name!r}. Focus the preview window and press 'q' to quit.")
        while True:
            frame = cap.grab()
            result = detector.measure(frame)

            display = frame.copy()
            _draw_result(display, icon_name, result, (0, 255, 0) if result.present else (0, 0, 255))
            cv2.imshow("Presence Test (q to quit)", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "single"
    icon_name = sys.argv[2] if len(sys.argv) > 2 else "hotel_return_icon"
    try:
        if mode == "single":
            single_check(icon_name)
        elif mode == "live":
            live_check(icon_name)
        else:
            print(f"Unknown mode: {mode!r} (use 'single' or 'live')")
            sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
