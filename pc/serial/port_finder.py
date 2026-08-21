"""Auto-detects the Arduino's COM port instead of requiring
pc/config/settings.yaml's serial.port to be updated by hand every time
the board re-enumerates -- which happens on every upload/reset. (COM16,
COM17, COM18, COM19... were all seen for the same physical board across
this project's development.)

Matches known Arduino VID:PID pairs first (most reliable), then falls
back to "Arduino" appearing in the port's description. That covers
genuine Arduino-brand boards (what this project has actually been
tested against) but not every clone -- a generic CH340-based clone with
no "Arduino" in its Windows-reported description won't be found this
way; set serial.port to a specific COM port in that case instead of
"auto".
"""
from __future__ import annotations

from typing import List, Optional

import serial.tools.list_ports as list_ports

# (vendor_id, product_id) pairs for genuine Arduino/SparkFun boards with
# native USB HID (32u4-based -- what this project needs; a plain Uno/Nano
# can't do keyboard/mouse HID at all regardless of port detection).
_KNOWN_ARDUINO_VID_PID = {
    (0x2341, 0x8036),  # Leonardo
    (0x2341, 0x8037),  # Micro
    (0x2341, 0x0036),  # Leonardo (bootloader)
    (0x2341, 0x0037),  # Micro (bootloader)
    (0x1B4F, 0x9206),  # SparkFun Pro Micro 5V/16MHz
    (0x1B4F, 0x9205),  # SparkFun Pro Micro 3.3V/8MHz
}


def find_arduino_ports() -> List[str]:
    """Return every COM port that looks like an Arduino, most confident
    match first (VID:PID match before description-only match)."""
    vid_pid_matches = []
    description_matches = []
    for port in list_ports.comports():
        if port.vid is not None and port.pid is not None and (port.vid, port.pid) in _KNOWN_ARDUINO_VID_PID:
            vid_pid_matches.append(port.device)
        elif port.description and "arduino" in port.description.lower():
            description_matches.append(port.device)
    return vid_pid_matches + description_matches


def resolve_port(configured_port: str) -> str:
    """If `configured_port` is "auto" (case-insensitive), auto-detect and
    return a port; otherwise return it unchanged (explicit config always wins).

    Raises RuntimeError if "auto" was requested but nothing was found, or
    prints a warning and picks the first match if more than one was found.
    """
    if configured_port.strip().lower() != "auto":
        return configured_port

    found = find_arduino_ports()
    if not found:
        raise RuntimeError(
            'serial.port is set to "auto" but no Arduino-looking COM port was found. '
            "Check the board is connected and drivers are installed, or set serial.port "
            "to a specific COM port (e.g. \"COM19\") in pc/config/settings.yaml instead."
        )
    if len(found) > 1:
        print(f"[warn] multiple Arduino-looking ports found {found}, using the first one: {found[0]}")
    return found[0]
