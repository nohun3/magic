"""[2단계] 여관 이동.

Two sub-actions, both plain quick-slot icon double-clicks (no dialog
involved):

1. `icons.hotel_key` -- a return-to-room item bound to a quick-slot
   icon; double-clicking it teleports the character straight to the
   rented hotel room. Followed by pressing ESC 3-5 times (per the
   user's request) to clear out whatever transient dialog/prompt the
   teleport itself might have left open.
2. `icons.meditation` -- double-clicked right after arriving, to start
   recovering.

The meditation double-click can silently fail to actually cast if MP is
too low right after a hunt (per the user, meditation requires MP >= 10
to cast at all) -- [2단계] always runs right after [4단계] exits at
MP <= 5%, so this is a real, not theoretical, case. After clicking, `run()` checks
`buffs.meditation` in `roi_buff` to confirm the buff actually came up;
if not, it waits for MP to passively regen back up to
MEDITATION_RETRY_MIN_MP and clicks icon_meditation once more -- then
checks the buff a *second* time. Confirmed live that this second check
matters: the retry click can ACK fine (the Arduino did physically
click) without the buff actually coming up in-game, so trusting the ACK
alone was reporting false successes. A missing buff after that retry is
logged as a warning but does not fail [2단계]; the caller continues to
wait for the configured HP/MP readiness condition.

Both icons live on the F2 quick-slot tab that `roi_skill`'s templates
were captured against -- the skill bar has multiple tabs (F1/F2/F3), so
F2 is (re-)pressed before each of the two detections rather than once
up front, in case the teleport itself resets the selected tab.

Precondition for sub-action 1 (checked by the caller, not here):
`icons.hotel_key` must already be present -- if it isn't, a room/key
hasn't been bought yet and [1단계] (여관 열쇠 구입) needs to run first
instead.

All mouse movement/clicking goes through the Arduino (SerialLink), never
a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.capture.screen_capture import Region  # noqa: E402
from pc.detector.any_presence_detector import AnyPresenceDetector, build_icon_detector  # noqa: E402
from pc.detector.presence_detector import PresenceResult  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.window_content import ContentOffset, WindowContentLocator  # noqa: E402
from pc.detector.chat_reader import KoreanTextReader  # noqa: E402
from pc.detector.remembered_text import RememberedDialogText  # noqa: E402
from pc.detector.color_mask import mask_non_yellow  # noqa: E402
from pc.detector.template_locator import locate_template  # noqa: E402
from pc.action.frame_to_mouse import FrameToMouseConverter  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.routine.timing import sleep_jittered  # noqa: E402

# How long to wait after pressing F2 before the tab swap has visibly
# finished (icons re-render) -- generous but this step only runs
# occasionally, not per-frame, so it doesn't need to be tight.
TAB_SWITCH_SETTLE_S = 0.3

# How long to wait after the hotel_key double-click before the teleport
# fade/load has finished and it's safe to recapture -- longer than a
# dialog opening (that's near-instant); a full scene teleport isn't.
TELEPORT_SETTLE_S = 1.5

# If the meditation buff didn't come up after the double-click, this is
# the raw MP value (not percent) to wait for before retrying the cast
# once -- per the user, meditation can only be cast at MP >= 10.
MEDITATION_RETRY_MIN_MP = 10
MP_POLL_INTERVAL_S = 1.0
EVENT_DIALOG_SETTLE_S = 0.6
EVENT_TELEPORT_SETTLE_S = 1.5
EVENT_NPC_SETTLE_S = 0.6
MAX_EVENT_RESTARTS_PER_STEP2 = 3
HASTE_KEY_HOLD_MIN_S = 6.0
HASTE_KEY_HOLD_MAX_S = 7.0
CLOSE_CLICK_SETTLE_S = 0.3
EVENT_MERCHANT_NEEDLES = ("기란", "잡화", "상인")

# Registered once by run_all after roi_chatting is located. All shared click
# helpers then park the cursor at a fresh random point in this region instead
# of repeatedly moving it to the game field's upper centre.
_cursor_park_region: Region | None = None


# After the hotel_key double-click, press ESC this many times (picked
# fresh each call) -- per the user's request, to clear out whatever
# transient dialog/prompt the teleport itself might have left open.
ESC_PRESSES_MIN = 3
ESC_PRESSES_MAX = 5


def build_hotel_key_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["hotel_key"], project_root, panel=skill_panel)


def build_meditation_icon_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["meditation"], project_root, panel=skill_panel)


def build_meditation_buff_detector(settings: dict, project_root: Path, buff_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["buffs"]["meditation"], project_root, panel=buff_panel)


def build_mana_buff_detector(settings: dict, project_root: Path, buff_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["buffs"]["mana"], project_root, panel=buff_panel)


def build_mana_icon_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["mana"], project_root, panel=skill_panel)


def build_haste_buff_detector(settings: dict, project_root: Path, buff_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["buffs"]["haste"], project_root, panel=buff_panel)


def build_event_buff_detector(settings: dict, project_root: Path, buff_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["buffs"]["event"], project_root, panel=buff_panel)


def build_talking_scroll_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["talking_scroll"], project_root, panel=skill_panel)


def _select_event_merchant(lines) -> Region | None:
    """Select ``[기란] 잡화 상인`` even when OCR splits one row.

    PaddleOCR can return the location, job, and NPC type as three adjacent
    boxes. Group boxes whose vertical centres belong to the same rendered
    row, then require all three needles in that combined row. Requiring
    ``기란`` prevents the later generic ``잡화 상인`` entry from matching.
    """
    for _, seed_box in lines:
        seed_center_y = seed_box.top + seed_box.height / 2
        row = [
            (text, box) for text, box in lines
            if abs((box.top + box.height / 2) - seed_center_y)
            <= max(seed_box.height, box.height) * 0.5
        ]
        row.sort(key=lambda item: item[1].left)
        combined = "".join("".join(text.split()) for text, _ in row)
        if not all(needle in combined for needle in EVENT_MERCHANT_NEEDLES):
            continue
        left = min(box.left for _, box in row)
        top = min(box.top for _, box in row)
        right = max(box.left + box.width for _, box in row)
        bottom = max(box.top + box.height for _, box in row)
        return Region(left=left, top=top, width=right - left, height=bottom - top)
    return None


def build_event_merchant_text_locator(settings: dict, project_root: Path,
                                      reader: KoreanTextReader) -> RememberedDialogText:
    dialog_cfg = settings["dialog"]
    border = SkillPanelLocator(
        project_root / dialog_cfg["template"],
        dialog_cfg.get("match_threshold", 0.85),
    )
    content = WindowContentLocator(
        border, ContentOffset(**dialog_cfg["content_offset"])
    )
    return RememberedDialogText(
        content,
        reader,
        _select_event_merchant,
        preprocess=mask_non_yellow,
        merge_rows=True,
    )


def diagnose_event_merchant_ocr(settings: dict, project_root: Path,
                                frame: np.ndarray,
                                reader: KoreanTextReader) -> None:
    """Log and save the exact pixels used by the event merchant OCR.

    This is deliberately best-effort: diagnostics must never replace the
    original "text not found" result with an unrelated file/OCR exception.
    """
    try:
        dialog_cfg = settings["dialog"]
        border = SkillPanelLocator(
            project_root / dialog_cfg["template"],
            dialog_cfg.get("match_threshold", 0.85),
        )
        content = WindowContentLocator(
            border, ContentOffset(**dialog_cfg["content_offset"])
        )
        crop = content.crop_content(frame)

        timestamp_ms = int(time.time() * 1000)
        output_dir = project_root / "output" / "event_merchant_ocr"
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_path = output_dir / f"{timestamp_ms}_frame.png"
        cv2.imwrite(str(frame_path), frame)
        print(f"  [event OCR] full frame saved: {frame_path}")

        if crop is None or crop.size == 0:
            print("  [event OCR] dialog content region not found")
            return

        masked = mask_non_yellow(crop)
        crop_path = output_dir / f"{timestamp_ms}_content.png"
        masked_path = output_dir / f"{timestamp_ms}_yellow_mask.png"
        cv2.imwrite(str(crop_path), crop)
        cv2.imwrite(str(masked_path), masked)
        print(f"  [event OCR] dialog content saved: {crop_path}")
        print(f"  [event OCR] yellow mask saved: {masked_path}")

        lines = reader.read_lines_with_boxes(masked)
        if not lines:
            print("  [event OCR] recognized 0 line(s) after yellow mask")
            return
        print(f"  [event OCR] recognized {len(lines)} line(s) after yellow mask:")
        for index, (text, box) in enumerate(lines, start=1):
            print(f"    [{index:02d}] {text!r} box={box}")
    except Exception as error:
        print(
            f"  [event OCR] diagnostic failed: "
            f"{type(error).__name__}: {error}"
        )


def build_buff_panel(settings: dict, project_root: Path) -> SkillPanelLocator:
    buff_roi_cfg = settings["roi_buff"]
    return SkillPanelLocator(project_root / buff_roi_cfg["template"], buff_roi_cfg["match_threshold"])


def _capture_for_buff_check(
    settings: dict,
    project_root: Path,
    window_title: str,
    link: SerialLink,
    screen_capture_cls,
) -> np.ndarray:
    """Close one visible full-screen icon_close before inspecting roi_buff."""
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    close_cfg = settings["icons"]["close"]
    close_template = cv2.imread(str(project_root / close_cfg["template"]))
    if close_template is None:
        print("  [buff check warn] icon_close template could not be loaded")
        return frame

    close_match = locate_template(
        frame, close_template, close_cfg.get("match_threshold", 0.85)
    )
    if close_match is None:
        return frame

    if not click_region_once(link, converter, close_match.region):
        print("  [buff check warn] icon_close click failed -- checking current frame")
        return frame

    print(
        f"  [buff check] icon_close found "
        f"(score={close_match.score:.3f}) -- clicked once"
    )
    sleep_jittered(CLOSE_CLICK_SETTLE_S)
    frame, _ = _capture_and_convert(window_title, screen_capture_cls)
    return frame


def is_meditation_buff_active(settings: dict, project_root: Path, frame: np.ndarray) -> PresenceResult:
    buff_panel = build_buff_panel(settings, project_root)
    return build_meditation_buff_detector(settings, project_root, buff_panel).measure(frame)


def ensure_skill_tab(link: SerialLink) -> bool:
    """roi_skill's templates (hotel_key, meditation, ...) were captured
    against the F2 quick-slot tab -- press F2 to make sure that tab is
    showing before any roi_skill-scoped detection runs. Returns False if
    the keypress wasn't ACKed."""
    ack = link.send_and_wait("KEY", "F2")
    if ack is None or not ack.ok:
        return False
    sleep_jittered(TAB_SWITCH_SETTLE_S)
    return True


def set_cursor_park_region(region: Region) -> None:
    global _cursor_park_region
    _cursor_park_region = region


def park_cursor(link: SerialLink, converter: FrameToMouseConverter) -> bool:
    """Move the cursor to a neutral point in the open game world (clear
    of hotbars/buff column/chat), so it doesn't sit on top of whatever
    icon was just clicked. Otherwise the next capture can pick up that
    icon's hover tooltip (e.g. meditation's "HP/MP 소모" readout) drawn
    over the icon itself, which looks like a UI change and throws off
    template matching -- see the conversation this was found in.
    Returns True only if the move was ACKed OK."""
    if _cursor_park_region is not None:
        fx = _cursor_park_region.left + random.uniform(
            _cursor_park_region.width * 0.05,
            _cursor_park_region.width * 0.95,
        )
        fy = _cursor_park_region.top + random.uniform(
            _cursor_park_region.height * 0.05,
            _cursor_park_region.height * 0.95,
        )
    else:
        fx = converter.frame_width * 0.5
        fy = converter.frame_height * 0.35
    ux, uy = converter.convert(fx, fy)
    ack = link.send_and_wait("MOUSE_MOVE", f"{ux} {uy}")
    return ack is not None and ack.ok


def double_click_region(link: SerialLink, converter: FrameToMouseConverter, region: Region) -> bool:
    """Double-click within the centered 30% of `region`, then park the
    cursor away from it. Returns True only if the move and both clicks were
    ACKed OK (parking failure doesn't fail the whole click -- the click
    itself already succeeded by that point)."""
    fx = region.left + random.uniform(region.width * 0.35, region.width * 0.65)
    fy = region.top + random.uniform(region.height * 0.35, region.height * 0.65)
    ux, uy = converter.convert(fx, fy)

    move_ack = link.send_and_wait("MOUSE_MOVE", f"{ux} {uy}")
    if move_ack is None or not move_ack.ok:
        return False
    sleep_jittered(0.15)
    click1 = link.send_and_wait("MOUSE_CLICK", "LEFT")
    if click1 is None or not click1.ok:
        return False
    sleep_jittered(0.12)
    click2 = link.send_and_wait("MOUSE_CLICK", "LEFT")
    if click2 is None or not click2.ok:
        return False
    sleep_jittered(0.1)
    park_cursor(link, converter)
    return True


def locate_hotel_key(settings: dict, project_root: Path, frame: np.ndarray, skill_panel: SkillPanelLocator) -> PresenceResult:
    return build_hotel_key_detector(settings, project_root, skill_panel).measure(frame)


def press_escape_keys(link: SerialLink) -> bool:
    count = random.randint(ESC_PRESSES_MIN, ESC_PRESSES_MAX)
    print(f"  pressing ESC x{count}...")
    for i in range(count):
        ack = link.send_and_wait("KEY", "ESC")
        if ack is None or not ack.ok:
            print(f"    ESC {i + 1}/{count} -> FAILED (missing ACK)")
            return False
        sleep_jittered(0.15)
    print(f"    ESC x{count} -> ok")
    return True


def locate_meditation_icon(settings: dict, project_root: Path, frame: np.ndarray, skill_panel: SkillPanelLocator) -> PresenceResult:
    return build_meditation_icon_detector(settings, project_root, skill_panel).measure(frame)


def _wait_for_mp_at_least(mp_detector, min_mp: int, window_title: str, screen_capture_cls, poll_interval_s: float = MP_POLL_INTERVAL_S) -> None:
    print(f"    MP >= {min_mp} 대기 중 (meditation 재시전용)...")
    while True:
        with screen_capture_cls(window_title=window_title) as cap:
            frame = cap.grab()
        result = mp_detector.measure(frame)
        if result is not None:
            mp = result.reading
            if mp.current >= min_mp:
                print(f"    MP {mp.current}/{mp.maximum} -- 대기 종료")
                return
        sleep_jittered(poll_interval_s)


def _verify_and_retry_meditation(settings: dict, project_root: Path, link: SerialLink, skill_panel: SkillPanelLocator,
                                  mp_detector, window_title: str, screen_capture_cls) -> bool:
    """Confirms the meditation double-click actually activated the buff
    (checks `buffs.meditation` in roi_buff); if not, waits for MP to
    passively regen to MEDITATION_RETRY_MIN_MP and clicks
    icon_meditation once more. See module docstring for why this exists
    -- the cast can silently fail when MP is very low, which is exactly
    the state [2단계] always starts in right after [4단계]."""
    buff_panel = build_buff_panel(settings, project_root)
    frame = _capture_for_buff_check(
        settings, project_root, window_title, link, screen_capture_cls
    )
    buff_result = build_meditation_buff_detector(settings, project_root, buff_panel).measure(frame)
    if buff_result.present:
        print("  meditation buff active -- ok")
        return True

    print(f"  meditation buff not active after double-click (score={buff_result.match_score:.3f}) -- likely too little MP to cast")
    _wait_for_mp_at_least(mp_detector, MEDITATION_RETRY_MIN_MP, window_title, screen_capture_cls)

    if not ensure_skill_tab(link):
        print("  [retry] F2 keypress not ACKed")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    meditation = locate_meditation_icon(settings, project_root, frame, skill_panel)
    if not meditation.present or meditation.region is None:
        print("  [retry] meditation icon not present")
        return False
    ok = double_click_region(link, converter, meditation.region)
    print(f"  [retry] meditation double-click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    # An ACK only confirms the Arduino physically clicked -- not that
    # the click actually landed on/activated the skill in-game (found
    # live: the retry click ACKed fine but the buff still hadn't come
    # up). Re-check the buff itself instead of trusting the ACK alone.
    sleep_jittered(0.6)
    frame = _capture_for_buff_check(
        settings, project_root, window_title, link, screen_capture_cls
    )
    retry_buff_result = build_meditation_buff_detector(settings, project_root, buff_panel).measure(frame)
    if retry_buff_result.present:
        print("  [retry] meditation buff active -- ok")
        return True
    print(
        f"  [retry] meditation buff still not active "
        f"(score={retry_buff_result.match_score:.3f}) -- continuing without stopping"
    )
    return True


def click_region_once(link: SerialLink, converter: FrameToMouseConverter,
                      region: Region) -> bool:
    """Single-click a random point in the centered 30% of a region."""
    fx = region.left + random.uniform(region.width * 0.35, region.width * 0.65)
    fy = region.top + random.uniform(region.height * 0.35, region.height * 0.65)
    ux, uy = converter.convert(fx, fy)
    move_ack = link.send_and_wait("MOUSE_MOVE", f"{ux} {uy}")
    if move_ack is None or not move_ack.ok:
        return False
    sleep_jittered(0.15)
    click_ack = link.send_and_wait("MOUSE_CLICK", "LEFT")
    if click_ack is None or not click_ack.ok:
        return False
    sleep_jittered(0.1)
    park_cursor(link, converter)
    return True


def _handle_event_if_present(
    settings: dict,
    project_root: Path,
    window_title: str,
    link: SerialLink,
    skill_panel: SkillPanelLocator,
    screen_capture_cls,
    event_merchant_text: RememberedDialogText,
    korean_reader: KoreanTextReader,
) -> bool | None:
    """Handle the event before meditation when buff_event is absent.

    Returns None when the event buff is present, True after completing the
    event path (the caller must restart Step 2), and False on a failed action.
    """
    if not settings.get("step2", {}).get("event_recovery_enabled", True):
        return None
    frame = _capture_for_buff_check(
        settings, project_root, window_title, link, screen_capture_cls
    )
    buff_panel = build_buff_panel(settings, project_root)
    event_buff = build_event_buff_detector(
        settings, project_root, buff_panel
    ).measure(frame)
    if event_buff.present:
        print(
            f"  [event] buff_event already present "
            f"(score={event_buff.match_score:.3f}) -- skipping event path"
        )
        return None

    print(
        f"  [event] buff_event not present "
        f"(score={event_buff.match_score:.3f}) -- starting event path"
    )
    if not ensure_skill_tab(link):
        print("  [event] F2 keypress not ACKed")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    scroll = build_talking_scroll_detector(
        settings, project_root, skill_panel
    ).measure(frame)
    if not scroll.present or scroll.region is None:
        print("  [event] icon_talking_scroll not present")
        return False
    if not double_click_region(link, converter, scroll.region):
        print("  [event] talking_scroll double-click failed")
        return False

    sleep_jittered(EVENT_DIALOG_SETTLE_S)
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    merchant = event_merchant_text.find(frame)
    if merchant is None:
        print("  [event] '[기란] 잡화 상인' text not found")
        diagnose_event_merchant_ocr(
            settings, project_root, frame, korean_reader
        )
        return False
    if not click_region_once(link, converter, merchant):
        print("  [event] '[기란] 잡화 상인' click failed")
        return False

    sleep_jittered(EVENT_TELEPORT_SETTLE_S)
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    npc_cfg = settings["npcs"]["event"]
    npc_template = cv2.imread(str(project_root / npc_cfg["template"]))
    if npc_template is None:
        print("  [event] npc_event template could not be loaded")
        return False
    npc_match = locate_template(
        frame, npc_template, npc_cfg.get("match_threshold", 0.85)
    )
    if npc_match is None:
        print("  [event] npc_event not found")
        return False
    if not click_region_once(link, converter, npc_match.region):
        print("  [event] npc_event click failed")
        return False
    print("  [event] npc_event clicked -- restarting [2단계]")
    sleep_jittered(EVENT_NPC_SETTLE_S)
    return True


def ensure_mana(settings: dict, project_root: Path, link: SerialLink,
                skill_panel: SkillPanelLocator, window_title: str,
                screen_capture_cls) -> None:
    """Activate mana buff when absent; absence/failure is non-fatal."""
    buff_panel = build_buff_panel(settings, project_root)
    frame = _capture_for_buff_check(
        settings, project_root, window_title, link, screen_capture_cls
    )
    mana_buff = build_mana_buff_detector(settings, project_root, buff_panel).measure(frame)
    if mana_buff.present:
        print("  mana buff active -- ok")
        return

    print(f"  mana buff not active (score={mana_buff.match_score:.3f}) -- looking for icon_mana")
    if not ensure_skill_tab(link):
        print("  [mana warn] F2 keypress not ACKed -- continuing to [3단계]")
        return

    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    mana_icon = build_mana_icon_detector(settings, project_root, skill_panel).measure(frame)
    if not mana_icon.present or mana_icon.region is None:
        print(f"  [mana warn] icon_mana not present (score={mana_icon.match_score:.3f}) -- continuing to [3단계]")
        return

    ok = double_click_region(link, converter, mana_icon.region)
    print(f"  [mana] double-click -> {'ok' if ok else 'FAILED (continuing to [3단계])'}")


def ensure_haste_before_step3(
    settings: dict,
    project_root: Path,
    link: SerialLink,
    window_title: str,
    screen_capture_cls,
) -> bool | None:
    """Apply haste when absent, then tell the caller to restart Step 2."""
    buff_panel = build_buff_panel(settings, project_root)
    frame = _capture_for_buff_check(
        settings, project_root, window_title, link, screen_capture_cls
    )
    haste_buff = build_haste_buff_detector(
        settings, project_root, buff_panel
    ).measure(frame)
    if haste_buff.present:
        print(
            f"  haste buff active (score={haste_buff.match_score:.3f}) "
            "-- proceeding to [3단계]"
        )
        return None

    hold_seconds = random.uniform(HASTE_KEY_HOLD_MIN_S, HASTE_KEY_HOLD_MAX_S)
    print(
        f"  haste buff not active (score={haste_buff.match_score:.3f}) "
        f"-- holding F6 for {hold_seconds:.1f}s"
    )
    key_down_ack = link.send_and_wait("KEYDOWN", "F6")
    if key_down_ack is None or not key_down_ack.ok:
        print("  [haste] F6 KEYDOWN not ACKed")
        return False

    key_up_ack = None
    try:
        hold_deadline = time.monotonic() + hold_seconds
        while True:
            remaining = hold_deadline - time.monotonic()
            if remaining <= 0:
                break
            sleep_jittered(min(1.0, remaining), jitter_seconds=0.0)
            if time.monotonic() < hold_deadline:
                # Keep Arduino's 5-second connection watchdog satisfied while
                # F6 is intentionally held for longer than that timeout.
                link.send("PING")
    finally:
        key_up_ack = link.send_and_wait("KEYUP", "F6")

    if key_up_ack is None or not key_up_ack.ok:
        print("  [haste] F6 KEYUP not ACKed")
        return False

    print(f"  [haste] F6 held for {hold_seconds:.1f}s and released -- restarting [2단계]")
    return True


def _capture_and_convert(window_title: str, screen_capture_cls):
    from pc.capture.window_locator import locate_window_region

    with screen_capture_cls(window_title=window_title) as cap:
        frame = cap.grab()
    logical_region = locate_window_region(window_title)
    converter = FrameToMouseConverter(logical_region, frame.shape)
    return frame, converter


def run(settings: dict, project_root: Path, window_title: str, link: SerialLink,
        skill_panel: SkillPanelLocator, mp_detector, screen_capture_cls,
        korean_reader: KoreanTextReader) -> bool:
    """Full step: hotel_key double-click (teleport to room), then
    meditation double-click (start recovering), then verify the
    meditation buff actually came up and retry once if not (see module
    docstring). Returns False as soon as any sub-action fails to find
    its icon or ACK."""
    event_merchant_text = build_event_merchant_text_locator(
        settings, project_root, korean_reader
    )
    event_restarts = 0
    while True:
        # -- sub-action 1: hotel_key --
        if not ensure_skill_tab(link):
            return False
        frame, converter = _capture_and_convert(window_title, screen_capture_cls)
        hotel_key = locate_hotel_key(settings, project_root, frame, skill_panel)
        if not hotel_key.present or hotel_key.region is None:
            return False
        if not double_click_region(link, converter, hotel_key.region):
            return False

        if not press_escape_keys(link):
            return False

        sleep_jittered(TELEPORT_SETTLE_S)

        event_result = _handle_event_if_present(
            settings, project_root, window_title, link, skill_panel,
            screen_capture_cls, event_merchant_text, korean_reader,
        )
        if event_result is False:
            return False
        if event_result is None:
            break
        event_restarts += 1
        if event_restarts >= MAX_EVENT_RESTARTS_PER_STEP2:
            print(
                f"  [event] restart limit ({MAX_EVENT_RESTARTS_PER_STEP2}) "
                "reached -- stopping to avoid an infinite loop"
            )
            return False

    # -- sub-action 2: meditation --
    # Do not toggle/cancel meditation when it is already active. The
    # icon is a toggle-like action in practice, so blindly double-
    # clicking it at every [2단계] entry can undo the state we need.
    frame = _capture_for_buff_check(
        settings, project_root, window_title, link, screen_capture_cls
    )
    meditation_buff = is_meditation_buff_active(settings, project_root, frame)
    if meditation_buff.present:
        print("  meditation buff already active -- skipping icon_meditation double-click")
    else:
        if not ensure_skill_tab(link):
            print("  [warn] meditation F2 tab switch failed -- continuing without meditation")
        else:
            frame, converter = _capture_and_convert(window_title, screen_capture_cls)
            meditation = locate_meditation_icon(settings, project_root, frame, skill_panel)
            if not meditation.present or meditation.region is None:
                print("  [warn] meditation icon not present -- continuing without meditation")
            elif not double_click_region(link, converter, meditation.region):
                print("  [warn] meditation double-click was not ACKed -- continuing without meditation")
            elif not _verify_and_retry_meditation(
                settings, project_root, link, skill_panel, mp_detector,
                window_title, screen_capture_cls,
            ):
                print("  [warn] meditation buff could not be confirmed -- continuing without meditation")

    # Mana belongs to the beginning of Step 2: check/activate it directly
    # after the meditation action, before the HP/MP readiness wait.
    ensure_mana(
        settings, project_root, link, skill_panel, window_title,
        screen_capture_cls,
    )

    return True


def main() -> None:
    from pc.config.config_loader import load_settings
    from pc.capture.screen_capture import ScreenCapture
    from pc.capture.window_locator import WindowNotFoundError
    from pc.serial.port_finder import resolve_port
    from pc.detector.hpmp import build_hp_mp_detectors
    from pc.detector.ocr_reader import GaugeTextReader

    settings = load_settings()
    window_title = settings["capture"]["window_title"]

    roi_skill_cfg = settings["roi_skill"]
    skill_panel = SkillPanelLocator(
        _PROJECT_ROOT / roi_skill_cfg["template"], roi_skill_cfg["match_threshold"],
        roi_skill_cfg.get("search_region"),
    )

    print("Loading OCR model (HP/MP)...")
    gauge_reader = GaugeTextReader()
    _, mp_detector = build_hp_mp_detectors(settings, _PROJECT_ROOT, gauge_reader)
    korean_reader = KoreanTextReader()

    serial_cfg = settings["serial"]
    try:
        with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
            sleep_jittered(2.5)  # Leonardo boot delay after port open
            link.send("PING")
            sleep_jittered(0.3)
            link.poll_acks()

            ok = run(
                settings, _PROJECT_ROOT, window_title, link, skill_panel,
                mp_detector, ScreenCapture, korean_reader,
            )
            if not ok:
                sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)

    OUTPUT_DIR = _PROJECT_ROOT / "output"
    OUTPUT_DIR.mkdir(exist_ok=True)
    with ScreenCapture(window_title=window_title) as cap:
        after = cap.grab()
    out_path = OUTPUT_DIR / "step_move_to_hotel_result.png"
    cv2.imwrite(str(out_path), after)
    print(f"Screenshot saved -> {out_path}")


if __name__ == "__main__":
    main()
