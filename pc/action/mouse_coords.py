"""Converts real screen pixel coordinates into the units HID-Project's
AbsoluteMouse.moveTo() expects on the Arduino side.

This conversion has to happen on the PC, not the Arduino, because only
the PC knows the screen resolution -- the Arduino just relays whatever
units it's given straight into moveTo().

AbsoluteMouse.moveTo(x, y) takes signed 16-bit input in [-32768, 32767],
but x=0 is horizontal CENTER of the screen, not the left edge: the
Arduino-side library remaps it to the actual 0..32767 HID report range
via `report = (input + 32768) / 2` (see AbsoluteMouseAPI.hpp). So to
reach a specific HID report value (0 = left/top edge, 32767 =
right/bottom edge), we solve that equation backwards:
    input = report * 2 - 32768
"""
from __future__ import annotations

_HID_MAX = 32767


def pixel_to_absolute_unit(pixel: int, screen_size: int) -> int:
    """Convert one axis of a screen pixel coordinate to AbsoluteMouse.moveTo() input units."""
    if screen_size <= 0:
        raise ValueError(f"screen_size must be positive, got {screen_size}")
    report = round(pixel / screen_size * _HID_MAX)
    report = max(0, min(_HID_MAX, report))
    return report * 2 - 32768


def pixel_to_absolute_mouse(x: int, y: int, screen_width: int, screen_height: int) -> tuple[int, int]:
    """Convert a (x, y) screen pixel coordinate to the (x, y) units
    expected by the Arduino's MOUSE_MOVE command."""
    return (
        pixel_to_absolute_unit(x, screen_width),
        pixel_to_absolute_unit(y, screen_height),
    )
