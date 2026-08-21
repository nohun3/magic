"""Locates the game window by title so capture doesn't depend on a
fixed screen position.

The game window's position/size can differ between runs (different
monitor, different spot on screen, etc.), but once the game is running
it doesn't move — so this module resolves the window's client-area
bounds once (on demand), not on every frame.
"""
from __future__ import annotations

from typing import List

import win32gui

from pc.capture.screen_capture import Region


class WindowNotFoundError(RuntimeError):
    """Raised when no visible window matches the requested title."""


def find_window_by_title(title_substring: str) -> int:
    """Return the hwnd of the first visible window whose title contains
    `title_substring` (case-insensitive).

    "First" follows Z-order from `EnumWindows` (topmost/foreground
    windows are enumerated first), so if multiple matching windows are
    open, the one most likely to be the active game client wins.
    """
    needle = title_substring.lower()
    matches: List[int] = []

    def _on_window(hwnd: int, _lparam) -> bool:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and needle in title.lower():
                matches.append(hwnd)
        return True  # keep enumerating

    win32gui.EnumWindows(_on_window, None)

    if not matches:
        raise WindowNotFoundError(
            f"No visible window with title containing {title_substring!r} was found. "
            "Make sure the game is running and not minimized."
        )
    return matches[0]


def get_client_region(hwnd: int) -> Region:
    """Return the window's client area (excludes title bar/borders) as a
    Region in screen coordinates."""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    screen_left, screen_top = win32gui.ClientToScreen(hwnd, (left, top))
    screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
    return Region(
        left=screen_left,
        top=screen_top,
        width=screen_right - screen_left,
        height=screen_bottom - screen_top,
    )


def locate_window_region(title_substring: str) -> Region:
    """Convenience: find the window and return its current client region."""
    hwnd = find_window_by_title(title_substring)
    return get_client_region(hwnd)
