"""Manual test: find on-screen Korean text by content and click it via
the Arduino -- e.g. open the talking-scroll location list and click a
specific destination entry by its label.

Usage (run from the project root, with the venv active):

    python -m pc.detector.test_click_text <needle> [needle2 ...]

Example:

    python -m pc.detector.test_click_text 오렌 여관

Assumes a dialog (templates/roi_dialog.png -- the generic popup frame
reused for talking-scroll/teleport-scroll lists, NPC dialogue, etc.) is
already open on screen -- this test only locates/reads/clicks within it,
it doesn't open it. OCR is scoped to `dialog.content_offset` (see
settings.yaml) instead of the whole frame, which is both faster and
avoids matching text in some unrelated part of the screen.

All mouse movement/clicking goes through the Arduino (SerialLink), never
a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import cv2
import mss

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.capture.screen_capture import ScreenCapture  # noqa: E402
from pc.capture.window_locator import WindowNotFoundError, locate_window_region  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.window_content import ContentOffset, WindowContentLocator  # noqa: E402
from pc.detector.chat_reader import KoreanTextReader, find_text_region  # noqa: E402
from pc.action.mouse_coords import pixel_to_absolute_mouse  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.serial.port_finder import resolve_port  # noqa: E402

OUTPUT_DIR = _PROJECT_ROOT / "output"


def _send_and_wait(link: SerialLink, cmd_type: str, args: str, timeout: float = 2.0) -> bool:
    t0 = time.perf_counter()
    cmd_id = link.send(cmd_type, args)
    while time.perf_counter() - t0 < timeout:
        for ack in link.poll_acks():
            if ack.command_id == cmd_id:
                print(f"  {cmd_type} {args} -> ok={ack.ok} {ack.detail}")
                return ack.ok
        time.sleep(0.01)
    print(f"  {cmd_type} {args} -> [warn] no ACK")
    return False


def main() -> None:
    needles = sys.argv[1:]
    if not needles:
        print("Usage: python -m pc.detector.test_click_text <needle> [needle2 ...]")
        sys.exit(1)

    settings = load_settings()
    window_title = settings["capture"]["window_title"]

    try:
        logical_region = locate_window_region(window_title)
        with ScreenCapture(window_title=window_title) as cap:
            frame = cap.grab()
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)

    scale_x = frame.shape[1] / logical_region.width
    scale_y = frame.shape[0] / logical_region.height

    dialog_cfg = settings["dialog"]
    border = SkillPanelLocator(_PROJECT_ROOT / dialog_cfg["template"], dialog_cfg.get("match_threshold", 0.85))
    content_locator = WindowContentLocator(border, ContentOffset(**dialog_cfg["content_offset"]))

    content_region = content_locator.content_region(frame)
    if content_region is None:
        print("Dialog not found on screen -- is it open?")
        sys.exit(1)
    crop = frame[
        content_region.top: content_region.top + content_region.height,
        content_region.left: content_region.left + content_region.width,
    ]
    print(f"Content region (frame px): {content_region} ({crop.shape[1]}x{crop.shape[0]}, "
          f"was a fixed 750x620 guess before -- {750 * 620 / (crop.shape[0] * crop.shape[1]):.1f}x less area)")

    print("Loading Korean OCR model...")
    reader = KoreanTextReader()
    t0 = time.perf_counter()
    lines = reader.read_lines_with_boxes(crop)
    print(f"OCR took {(time.perf_counter() - t0) * 1000:.0f}ms, found {len(lines)} lines")

    target = find_text_region(lines, *needles)
    if target is None:
        print(f"\n{' + '.join(needles)!r} not found. Lines seen:")
        for text, _box in lines:
            print(f"  {text!r}")
        sys.exit(0)

    print(f"\nFound target region (content-local): {target}")

    fx = content_region.left + target.left + random.uniform(target.width * 0.15, target.width * 0.85)
    fy = content_region.top + target.top + random.uniform(target.height * 0.2, target.height * 0.8)
    logical_x = logical_region.left + fx / scale_x
    logical_y = logical_region.top + fy / scale_y

    with mss.mss() as sct:
        monitor = sct.monitors[1]
    logical_screen_w = monitor["width"] / scale_x
    logical_screen_h = monitor["height"] / scale_y
    ux, uy = pixel_to_absolute_mouse(
        round(logical_x), round(logical_y), round(logical_screen_w), round(logical_screen_h)
    )
    print(f"Click point (frame px): ({fx:.1f},{fy:.1f}) -> AbsoluteMouse units ({ux},{uy})")

    serial_cfg = settings["serial"]
    with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
        time.sleep(2.5)  # Leonardo boot delay after port open
        link.send("PING")
        time.sleep(0.3)
        link.poll_acks()

        _send_and_wait(link, "MOUSE_MOVE", f"{ux} {uy}")
        time.sleep(0.15)
        _send_and_wait(link, "MOUSE_CLICK", "LEFT")
        time.sleep(0.6)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with ScreenCapture(window_title=window_title) as cap:
        after = cap.grab()
    out_path = OUTPUT_DIR / "click_text_result.png"
    cv2.imwrite(str(out_path), after)
    print(f"Screenshot saved -> {out_path}")


if __name__ == "__main__":
    main()
