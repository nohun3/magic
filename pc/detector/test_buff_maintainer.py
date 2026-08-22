"""Manual test: if the meditation buff isn't active, double-click its
skill icon (via Arduino) to reactivate it.

Usage (run from the project root, with the venv active):

    python -m pc.detector.test_buff_maintainer

roi_buff is located once at startup and that position is trusted from
then on ("remembered", per skill_panel.py's caching) rather than
re-verified every check -- its content changes too much (whichever
buffs are active) for an ongoing per-check match to be reliable, see
the comments in pc/config/settings.yaml.

All mouse movement/clicking goes through the Arduino (SerialLink),
never a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import cv2

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.capture.screen_capture import ScreenCapture  # noqa: E402
from pc.capture.window_locator import WindowNotFoundError, locate_window_region  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.any_presence_detector import build_icon_detector  # noqa: E402
from pc.detector.buff_maintainer import BuffMaintainer  # noqa: E402
from pc.action.frame_to_mouse import FrameToMouseConverter  # noqa: E402
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
    settings = load_settings()
    window_title = settings["capture"]["window_title"]

    try:
        logical_region = locate_window_region(window_title)
        with ScreenCapture(window_title=window_title) as cap:
            frame = cap.grab()
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)

    print("Locating roi_buff (remembered for the rest of this run)...")
    roi_buff_cfg = settings["roi_buff"]
    buff_panel = SkillPanelLocator(_PROJECT_ROOT / roi_buff_cfg["template"], roi_buff_cfg["match_threshold"])
    buff_panel_region = buff_panel.locate(frame)
    if buff_panel_region is None:
        print("[error] could not locate roi_buff at all -- is the game window in a normal state?")
        sys.exit(1)
    print(f"  roi_buff @ {buff_panel_region}")

    meditation_buff_detector = build_icon_detector(settings["buffs"]["meditation"], _PROJECT_ROOT, panel=buff_panel)

    skill_panel = SkillPanelLocator(_PROJECT_ROOT / settings["roi_skill"]["template"], settings["roi_skill"]["match_threshold"])
    meditation_icon_detector = build_icon_detector(settings["icons"]["meditation"], _PROJECT_ROOT, panel=skill_panel)

    maintainer = BuffMaintainer(meditation_buff_detector, meditation_icon_detector, cooldown_seconds=5.0)

    result = maintainer.check(frame)
    if not result.needs_reactivation:
        buff_now = meditation_buff_detector.measure(frame)
        print(f"Meditation buff present={buff_now.present} (score={buff_now.match_score:.3f}) -- nothing to do.")
        return

    print(f"Meditation buff missing -- double-clicking skill icon @ {result.skill_icon_region}")

    converter = FrameToMouseConverter(logical_region, frame.shape)
    region = result.skill_icon_region
    fx = region.left + random.uniform(region.width * 0.2, region.width * 0.8)
    fy = region.top + random.uniform(region.height * 0.2, region.height * 0.8)
    ux, uy = converter.convert(fx, fy)

    serial_cfg = settings["serial"]
    with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
        time.sleep(2.5)  # Leonardo boot delay after port open
        link.send("PING")
        time.sleep(0.3)
        link.poll_acks()

        _send_and_wait(link, "MOUSE_MOVE", f"{ux} {uy}")
        time.sleep(0.15)
        _send_and_wait(link, "MOUSE_CLICK", "LEFT")
        time.sleep(0.12)
        _send_and_wait(link, "MOUSE_CLICK", "LEFT")
        time.sleep(0.6)

    OUTPUT_DIR.mkdir(exist_ok=True)
    with ScreenCapture(window_title=window_title) as cap:
        after = cap.grab()
    out_path = OUTPUT_DIR / "buff_maintainer_result.png"
    cv2.imwrite(str(out_path), after)
    print(f"Screenshot saved -> {out_path}")


if __name__ == "__main__":
    main()
