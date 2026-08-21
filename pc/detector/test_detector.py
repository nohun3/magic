"""Manual test for development Step 2: HP/MP detection (template match + OCR).

Usage (run from the project root, with the venv active):

    python -m pc.detector.test_detector single   # one reading, prints HP/MP, saves debug overlay
    python -m pc.detector.test_detector live      # continuous readings, 'q' to quit

Compare the printed values against the actual "HP:x/y" / "MP:x/y" text
on screen to confirm the detectors are reading correctly. OCR model
loading takes a few seconds on startup -- that's expected.
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
from pc.detector.hpmp import build_hp_mp_detectors  # noqa: E402
from pc.detector.ocr_reader import GaugeTextReader  # noqa: E402
from pc.detector.gauge_detector import GaugeDetectionResult  # noqa: E402

OUTPUT_DIR = _PROJECT_ROOT / "output"


def _build_capture(settings: dict) -> ScreenCapture:
    cap_cfg = settings["capture"]
    if cap_cfg.get("window_title"):
        return ScreenCapture(window_title=cap_cfg["window_title"])
    region = Region(**cap_cfg["region"]) if cap_cfg.get("region") else None
    return ScreenCapture(monitor=cap_cfg.get("monitor", 1), region=region)


def _draw_result(frame, label: str, result: GaugeDetectionResult | None, color) -> None:
    if result is None:
        cv2.putText(frame, f"{label}: NOT FOUND", (20, 40 if label == "HP" else 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return
    roi = result.region
    top_left = (roi.left, roi.top)
    bottom_right = (roi.left + roi.width, roi.top + roi.height)
    cv2.rectangle(frame, top_left, bottom_right, color, 2)
    text = f"{label} {result.reading.current}/{result.reading.maximum} ({result.reading.percent:.1f}%)"
    cv2.putText(frame, text, (roi.left, roi.top - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def single_reading() -> None:
    settings = load_settings()
    print("Loading OCR model...")
    reader = GaugeTextReader()
    hp_detector, mp_detector = build_hp_mp_detectors(settings, _PROJECT_ROOT, reader)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with _build_capture(settings) as cap:
        frame = cap.grab()

    t0 = time.perf_counter()
    hp_result = hp_detector.measure(frame)
    mp_result = mp_detector.measure(frame)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if hp_result:
        r = hp_result.reading
        print(f"HP: {r.current}/{r.maximum} ({r.percent:.1f}%) [match={hp_result.match_score:.3f}]")
    else:
        print("HP: not found")

    if mp_result:
        r = mp_result.reading
        print(f"MP: {r.current}/{r.maximum} ({r.percent:.1f}%) [match={mp_result.match_score:.3f}]")
    else:
        print("MP: not found")

    print(f"Detection time (both bars): {elapsed_ms:.1f} ms")

    debug = frame.copy()
    _draw_result(debug, "HP", hp_result, (0, 255, 0))
    _draw_result(debug, "MP", mp_result, (0, 255, 255))
    out_path = OUTPUT_DIR / "detector_test.png"
    cv2.imwrite(str(out_path), debug)
    print(f"Debug overlay saved -> {out_path}")


def live_readings() -> None:
    settings = load_settings()
    print("Loading OCR model...")
    reader = GaugeTextReader()
    hp_detector, mp_detector = build_hp_mp_detectors(settings, _PROJECT_ROOT, reader)

    with _build_capture(settings) as cap:
        print("Live detection started. Focus the preview window and press 'q' to quit.")
        while True:
            frame = cap.grab()
            t0 = time.perf_counter()
            hp_result = hp_detector.measure(frame)
            mp_result = mp_detector.measure(frame)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            display = frame.copy()
            _draw_result(display, "HP", hp_result, (0, 255, 0))
            _draw_result(display, "MP", mp_result, (0, 255, 255))
            cv2.putText(display, f"OCR: {elapsed_ms:.0f} ms", (20, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Detector Test (q to quit)", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cv2.destroyAllWindows()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "single"
    try:
        if mode == "single":
            single_reading()
        elif mode == "live":
            live_readings()
        else:
            print(f"Unknown mode: {mode!r} (use 'single' or 'live')")
            sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
