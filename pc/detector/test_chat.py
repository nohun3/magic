"""Manual test for dungeon-entry remaining-time detection (chat log OCR).

Usage (run from the project root, with the venv active):

    python -m pc.detector.test_chat single   # one reading, saves debug overlay
    python -m pc.detector.test_chat live      # continuous readings, 'q' to quit

Prints the parsed minutes-remaining, or "no dungeon-time message found"
if the chat log doesn't currently contain one (normal -- it's not
always on screen, unlike HP/MP which are always visible).
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
from pc.detector.gauge_detector import GaugeDetector  # noqa: E402
from pc.detector.chat_reader import DungeonTimeReader, KoreanTextReader  # noqa: E402

OUTPUT_DIR = _PROJECT_ROOT / "output"


def _build_capture(settings: dict) -> ScreenCapture:
    cap_cfg = settings["capture"]
    if cap_cfg.get("window_title"):
        return ScreenCapture(window_title=cap_cfg["window_title"])
    region = Region(**cap_cfg["region"]) if cap_cfg.get("region") else None
    return ScreenCapture(monitor=cap_cfg.get("monitor", 1), region=region)


def _build_detector(settings: dict, reader: KoreanTextReader) -> GaugeDetector:
    chat_cfg = settings["chat"]
    dungeon_reader = DungeonTimeReader(reader)
    return GaugeDetector(_PROJECT_ROOT / chat_cfg["template"], dungeon_reader, chat_cfg.get("match_threshold", 0.5))


def _draw_result(frame, result) -> None:
    if result is None:
        cv2.putText(frame, "dungeon time: no message found", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return
    roi = result.region
    cv2.rectangle(frame, (roi.left, roi.top), (roi.left + roi.width, roi.top + roi.height), (0, 255, 0), 2)
    text = f"dungeon time: {result.reading.minutes_remaining} min left (match={result.match_score:.2f})"
    cv2.putText(frame, text, (roi.left, roi.top - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)


def single_check() -> None:
    settings = load_settings()
    print("Loading OCR model...")
    reader = KoreanTextReader()
    detector = _build_detector(settings, reader)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with _build_capture(settings) as cap:
        frame = cap.grab()

    result = detector.measure(frame)
    if result is None:
        print("No dungeon-time message currently in the chat log.")
    else:
        print(f"Dungeon time remaining: {result.reading.minutes_remaining} min "
              f"[match={result.match_score:.3f}]")

    debug = frame.copy()
    _draw_result(debug, result)
    out_path = OUTPUT_DIR / "chat_test.png"
    cv2.imwrite(str(out_path), debug)
    print(f"Debug overlay saved -> {out_path}")


def live_check() -> None:
    settings = load_settings()
    print("Loading OCR model...")
    reader = KoreanTextReader()
    detector = _build_detector(settings, reader)

    with _build_capture(settings) as cap:
        print("Live chat/dungeon-time check. Focus the preview window and press 'q' to quit.")
        while True:
            frame = cap.grab()
            result = detector.measure(frame)

            display = frame.copy()
            _draw_result(display, result)
            cv2.imshow("Chat/Dungeon-Time Test (q to quit)", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "single"
    try:
        if mode == "single":
            single_check()
        elif mode == "live":
            live_check()
        else:
            print(f"Unknown mode: {mode!r} (use 'single' or 'live')")
            sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
