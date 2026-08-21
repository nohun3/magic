"""Manual test for development Step 6: Arduino keyboard HID.

Usage (run from the project root, with the venv active):

    python -m pc.serial.test_keyboard

This sends real USB HID keystrokes -- whatever window has focus when
each command arrives will actually receive them. The script gives you a
5-second countdown to click into a text editor (Notepad, etc.) first.

Exercises: single-key tap, a Shift+1 combo ("!"), manual keydown/keyup
hold, an unknown key name (expect UNKNOWN_KEY), and STOP (release-all).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.serial.port_finder import resolve_port  # noqa: E402


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


def main() -> None:
    settings = load_settings()
    serial_cfg = settings["serial"]

    print("Focus a text editor (Notepad, etc.) now -- these are real keystrokes.")
    for i in range(5, 0, -1):
        print(f"  starting in {i}...")
        time.sleep(1)

    with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
        time.sleep(2.5)  # Leonardo boot delay after port open
        link.send("PING")
        time.sleep(0.3)
        link.poll_acks()

        print("Sending: single key taps 'H' 'I'")
        _send_and_wait(link, "KEY", "H")
        time.sleep(0.1)
        _send_and_wait(link, "KEY", "I")

        time.sleep(0.5)
        print("Sending: KEYCOMBO SHIFT+1 (should type '!')")
        _send_and_wait(link, "KEYCOMBO", "SHIFT+1")

        time.sleep(0.5)
        print("Sending: KEYDOWN SPACE / KEYUP SPACE (manual hold)")
        _send_and_wait(link, "KEYDOWN", "SPACE")
        time.sleep(0.2)
        _send_and_wait(link, "KEYUP", "SPACE")

        time.sleep(0.5)
        print("Sending: unsupported key name (expect UNKNOWN_KEY)")
        _send_and_wait(link, "KEY", "NOTAKEY")

        time.sleep(0.5)
        print("Sending: STOP (release-all safety command)")
        _send_and_wait(link, "STOP", "")

    print("\nDone. Check the text editor -- it should read: HI! (with a trailing space)")


if __name__ == "__main__":
    main()
