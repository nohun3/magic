"""Manual test for development Step 1: screen capture.

Usage (run from the project root, with the venv active):

    python -m pc.capture.test_capture single   # grab one frame, save to output/capture_test.png
    python -m pc.capture.test_capture live      # live preview window with FPS overlay, 'q' to quit

`single` is the quick sanity check: run it, then open output/capture_test.png
and confirm it matches what's on your screen.

`live` is for confirming the capture loop can sustain the configured
target_fps before later steps (HP/MP detection, condition checks) add
more work on top of it.
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

OUTPUT_DIR = _PROJECT_ROOT / "output"


def _build_capture(settings: dict) -> ScreenCapture:
    cap_cfg = settings["capture"]
    if cap_cfg.get("window_title"):
        try:
            return ScreenCapture(window_title=cap_cfg["window_title"])
        except WindowNotFoundError as e:
            print(f"[capture] {e}")
            raise
    region = Region(**cap_cfg["region"]) if cap_cfg.get("region") else None
    return ScreenCapture(monitor=cap_cfg.get("monitor", 1), region=region)


def capture_single() -> None:
    settings = load_settings()
    OUTPUT_DIR.mkdir(exist_ok=True)
    with _build_capture(settings) as cap:
        frame = cap.grab()
        out_path = OUTPUT_DIR / "capture_test.png"
        cv2.imwrite(str(out_path), frame)
        print(f"Captured {frame.shape[1]}x{frame.shape[0]} frame -> {out_path}")


def capture_live() -> None:
    settings = load_settings()
    target_fps = settings["capture"].get("target_fps", 30)
    frame_interval = 1.0 / target_fps

    with _build_capture(settings) as cap:
        print("Live preview started. Focus the preview window and press 'q' to quit.")
        last_time = time.perf_counter()
        fps = 0.0
        while True:
            loop_start = time.perf_counter()

            frame = cap.grab()

            now = time.perf_counter()
            dt = now - last_time
            last_time = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)

            display = frame.copy()
            cv2.putText(
                display, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2,
            )
            cv2.imshow("Screen Capture Test (q to quit)", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            elapsed = time.perf_counter() - loop_start
            remaining = frame_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    cv2.destroyAllWindows()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "single"
    if mode == "single":
        capture_single()
    elif mode == "live":
        capture_live()
    else:
        print(f"Unknown mode: {mode!r} (use 'single' or 'live')")
        sys.exit(1)


if __name__ == "__main__":
    main()
