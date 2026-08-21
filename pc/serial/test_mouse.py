"""Manual test for development Step 7: Arduino mouse HID (absolute move + click).

Usage (run from the project root, with the venv active):

    python -m pc.serial.test_mouse move   # only: move to known points, verify via GetCursorPos (no visible side effects beyond the cursor itself moving)
    python -m pc.serial.test_mouse click  # only: right-click on desktop + screenshot + Escape, MOUSE_DOWN/UP, error case, STOP
    python -m pc.serial.test_mouse full   # both (default)

`move` moves the real OS cursor to a handful of known screen pixel
coordinates and reads back the actual position via GetCursorPos() to
verify absolute positioning accuracy directly (no eyeballing needed).

`click` right-clicks on an empty desktop area and takes a screenshot so
you can confirm the context menu actually appeared (visual proof the
click HID report reached Windows), dismisses it with Escape, and
exercises MOUSE_DOWN/MOUSE_UP, an unknown-button error case, and STOP.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import win32api

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.serial.port_finder import resolve_port  # noqa: E402
from pc.action.mouse_coords import pixel_to_absolute_mouse  # noqa: E402
from pc.capture.screen_capture import ScreenCapture  # noqa: E402

OUTPUT_DIR = _PROJECT_ROOT / "output"


def _send_and_wait(link: SerialLink, cmd_type: str, args: str, timeout: float = 2.0) -> bool:
    t0 = time.perf_counter()
    cmd_id = link.send(cmd_type, args)
    while time.perf_counter() - t0 < timeout:
        for ack in link.poll_acks():
            if ack.command_id == cmd_id:
                status = "OK" if ack.ok else f"ERR {ack.detail}"
                print(f"  id={cmd_id} {cmd_type} {args} -> {status}")
                return ack.ok
        time.sleep(0.005)
    print(f"  id={cmd_id} {cmd_type} {args} -> [warn] no ACK")
    return False


def _connect(serial_cfg: dict) -> SerialLink:
    link = SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"])
    time.sleep(2.5)  # Leonardo boot delay after port open
    link.send("PING")
    time.sleep(0.3)
    link.poll_acks()
    return link


def run_move_test(link: SerialLink, screen_w: int, screen_h: int) -> None:
    print("\n-- Absolute move accuracy --")
    targets = [
        (screen_w // 2, screen_h // 2, "center"),
        (100, 100, "near top-left"),
        (screen_w - 100, screen_h - 100, "near bottom-right"),
    ]
    max_error = 0
    for px, py, label in targets:
        ux, uy = pixel_to_absolute_mouse(px, py, screen_w, screen_h)
        _send_and_wait(link, "MOUSE_MOVE", f"{ux} {uy}")
        time.sleep(0.1)
        actual_x, actual_y = win32api.GetCursorPos()
        err_x, err_y = abs(actual_x - px), abs(actual_y - py)
        max_error = max(max_error, err_x, err_y)
        print(f"  {label}: target=({px},{py}) actual=({actual_x},{actual_y}) error=({err_x},{err_y})px")
    print(f"Max positioning error: {max_error}px")


def run_click_test(link: SerialLink, screen_w: int, screen_h: int) -> None:
    print("\n-- Click test (right-click on desktop, screenshot the context menu) --")
    px, py = screen_w // 2, screen_h // 2
    ux, uy = pixel_to_absolute_mouse(px, py, screen_w, screen_h)
    _send_and_wait(link, "MOUSE_MOVE", f"{ux} {uy}")
    time.sleep(0.1)
    _send_and_wait(link, "MOUSE_CLICK", "RIGHT")
    time.sleep(0.3)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with ScreenCapture(monitor=1) as cap:
        frame = cap.grab()
    out_path = OUTPUT_DIR / "mouse_click_test.png"
    cv2.imwrite(str(out_path), frame)
    print(f"Screenshot saved -> {out_path} (check for a context menu)")

    _send_and_wait(link, "KEY", "ESC")  # dismiss whatever menu may have opened

    print("\n-- MOUSE_DOWN / MOUSE_UP --")
    _send_and_wait(link, "MOUSE_DOWN", "LEFT")
    time.sleep(0.1)
    _send_and_wait(link, "MOUSE_UP", "LEFT")

    print("\n-- Unknown button (expect UNKNOWN_BUTTON) --")
    _send_and_wait(link, "MOUSE_CLICK", "NOTABUTTON")

    print("\n-- STOP (release-all safety command) --")
    _send_and_wait(link, "STOP", "")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode not in ("move", "click", "full"):
        print(f"Unknown mode: {mode!r} (use 'move', 'click', or 'full')")
        sys.exit(1)

    settings = load_settings()
    serial_cfg = settings["serial"]

    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)
    print(f"Screen resolution: {screen_w}x{screen_h}")

    with _connect(serial_cfg) as link:
        if mode in ("move", "full"):
            run_move_test(link, screen_w, screen_h)
        if mode in ("click", "full"):
            run_click_test(link, screen_w, screen_h)


if __name__ == "__main__":
    main()
