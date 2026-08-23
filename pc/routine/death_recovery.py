"""Cooperative death-dialog recovery shared by routine steps 1 through 4."""
from __future__ import annotations

import random
from pathlib import Path

import cv2

from pc.action.frame_to_mouse import FrameToMouseConverter
from pc.capture.screen_capture import Region
from pc.capture.window_locator import locate_window_region
from pc.detector.template_locator import locate_template
from pc.routine.step_move_to_hotel import park_cursor
from pc.routine.timing import sleep_jittered
from pc.serial.serial_link import SerialLink


class DeathRecoveryRequested(Exception):
    """Raised after death handling so run_all restarts from Step 2."""


class DeathRecoveryController:
    def __init__(self, settings: dict, project_root: Path, window_title: str,
                 link: SerialLink):
        config = settings.get("death_recovery", {})
        self._dialog = cv2.imread(
            str(project_root / config.get("dialog_template", "templates/dialog_restart.png"))
        )
        self._icon = cv2.imread(
            str(project_root / config.get("icon_template", "templates/icon_restart.png"))
        )
        if self._dialog is None or self._icon is None:
            raise FileNotFoundError("death recovery templates could not be loaded")
        self._dialog_threshold = float(config.get("dialog_match_threshold", 0.85))
        self._icon_threshold = float(config.get("icon_match_threshold", 0.85))
        self._window_title = window_title
        self._link = link

    def check(self, frame) -> None:
        dialog_match = locate_template(frame, self._dialog, self._dialog_threshold)
        if dialog_match is None:
            return

        dialog = dialog_match.region
        crop = frame[
            dialog.top:dialog.top + dialog.height,
            dialog.left:dialog.left + dialog.width,
        ]
        icon_match = locate_template(crop, self._icon, self._icon_threshold)
        if icon_match is None:
            print(
                f"[death] dialog_restart detected (score={dialog_match.score:.3f}), "
                "but icon_restart was not found"
            )
            raise DeathRecoveryRequested("icon_restart not found")

        local = icon_match.region
        icon = Region(
            left=dialog.left + local.left,
            top=dialog.top + local.top,
            width=local.width,
            height=local.height,
        )
        converter = FrameToMouseConverter(
            locate_window_region(self._window_title), frame.shape
        )
        # Single click, using the same centered-30% target policy as all
        # other image regions in the routine.
        fx = icon.left + icon.width * random.uniform(0.35, 0.65)
        fy = icon.top + icon.height * random.uniform(0.35, 0.65)
        ux, uy = converter.convert(fx, fy)
        move_ack = self._link.send_and_wait("MOUSE_MOVE", f"{ux} {uy}")
        if move_ack is None or not move_ack.ok:
            raise DeathRecoveryRequested("icon_restart mouse move not ACKed")
        sleep_jittered(0.15)
        click_ack = self._link.send_and_wait("MOUSE_CLICK", "LEFT")
        if click_ack is None or not click_ack.ok:
            raise DeathRecoveryRequested("icon_restart click not ACKed")
        print(
            f"[death] dialog_restart detected (score={dialog_match.score:.3f}); "
            f"icon_restart clicked once (score={icon_match.score:.3f})"
        )
        sleep_jittered(0.6)
        park_cursor(self._link, converter)
        raise DeathRecoveryRequested("restart clicked")


class DeathAwareScreenCapture:
    """ScreenCapture proxy that checks every captured routine frame."""

    def __init__(self, base_capture_cls, controller: DeathRecoveryController,
                 *args, **kwargs):
        self._capture = base_capture_cls(*args, **kwargs)
        self._controller = controller

    def grab(self):
        frame = self._capture.grab()
        self._controller.check(frame)
        return frame

    def close(self) -> None:
        self._capture.close()

    def __enter__(self):
        self._capture.__enter__()
        return self

    def __exit__(self, *exc):
        return self._capture.__exit__(*exc)

