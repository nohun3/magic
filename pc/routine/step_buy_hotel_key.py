"""[1단계] 여관 열쇠 구입.

[2단계](step_move_to_hotel.py)를 실행하기 전, `icons.hotel_key`가
roi_skill에 없으면(아직 방을 안 구했으면) 먼저 이 스텝을 실행해서 방을
구해야 한다 -- 그 판단(precondition)은 이 모듈이 아니라 호출하는 쪽
(나중에 만들 StepRunner)의 책임이고, 여기는 "산다"는 동작 자체만 한다.

5개의 서브액션, 전부 오늘 세션에서 개별적으로 검증된 패턴을 그대로 이어붙인
것:

1. roi_skill에서 icon_talking_scroll 더블클릭 -> 대화창 오픈 (F2 탭,
   step_move_to_hotel의 ensure_skill_tab()/double_click_region() 재사용)
2. dialog 영역에서 "[오렌] 여관" 텍스트를 원클릭 -> 오렌 마을 여관으로 텔레포트
3. npc_hotel_manager 이미지와 가장 비슷한 부분(월드 공간, 화면 전체 검색)을
   원클릭 -> "엔케" NPC와 대화 시작 (step_move_to_wasteland의
   npc_teleport_gate와 동일한 이유로 이름표 텍스트가 아니라 스프라이트를
   클릭 -- NPC 대화는 오늘 세션에서 실제로 이 방식이어야 열린다는 걸 확인함)
4. dialog 영역에서 "방을 대여한다" 텍스트를 찾아 원클릭
5. dialog 영역 하단의 "OK" 버튼을 찾아 원클릭 (방 대여 최종 확인 프롬프트로 추정)

세 번의 텍스트 찾기(2, 4, 5번)는 서로 다른 시점에 서로 다른 내용으로 열리는
dialog(대화창 목록 / NPC 대화 / 확인 프롬프트)라서, RememberedDialogText도
텍스트별로 별개 인스턴스를 하나씩 둔다(캐시를 공유하면 안 됨) -- OCR은 각각
최초 1회만 돌고, 그 뒤로는 dialog anchor(OCR 아닌, 싼 템플릿 매칭)만 다시 맞춰서
기억해둔 위치를 클릭한다. pc/detector/remembered_text.py 참고.

2번("[오렌] 여관")과 4번("방을 대여한다")은 노란색 텍스트라서 OCR 전에
pc/detector/color_mask.py의 mask_non_yellow()로 노란색만 남기고 마스킹한다 --
step_move_to_wasteland.py의 게이트 이후 대화창들과 같은 이유로 훨씬 빠르다. 5번
("OK")은 검은색 버튼 라벨이라 노란색 마스킹 대상이 아니다.

All mouse movement/clicking goes through the Arduino (SerialLink), never
a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.detector.any_presence_detector import AnyPresenceDetector, build_icon_detector  # noqa: E402
from pc.detector.presence_detector import PresenceResult  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.window_content import ContentOffset, WindowContentLocator  # noqa: E402
from pc.detector.chat_reader import KoreanTextReader, needles_match_fn  # noqa: E402
from pc.detector.remembered_text import RememberedDialogText, first_matching  # noqa: E402
from pc.detector.color_mask import mask_non_yellow  # noqa: E402
from pc.detector.template_locator import locate_template  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.routine.step_move_to_hotel import ensure_skill_tab, double_click_region, park_cursor, _capture_and_convert  # noqa: E402
from pc.routine.step_move_to_wasteland import click_region_once, SPRITE_CLICK_JITTER  # noqa: E402
from pc.routine.timing import sleep_jittered  # noqa: E402

# How long to wait after double-clicking talking_scroll before the
# dialog has finished opening/rendering.
DIALOG_OPEN_SETTLE_S = 0.6

# How long to wait after teleporting to the inn before it's safe to
# recapture and look for the hotel_manager NPC sprite.
TELEPORT_SETTLE_S = 1.5

# How long to wait after clicking the NPC / a menu entry before the next
# dialog/prompt has finished rendering.
DIALOG_STEP_SETTLE_S = 0.6

HOTEL_NEEDLES = ("오렌", "여관")
RENT_ROOM_NEEDLES = ("방을", "대여한다")
OK_NEEDLES = ("OK",)


def _select_rent_room(lines):
    """Select the room-rental row even when OCR splits ``방을``.

    On the live dialog PaddleOCR has been observed to return the first
    row as two boxes, ``바`` and ``을대여한다``.  Requiring both original
    needles in one box therefore misses text that is visibly present.
    The adjacent hall-rental row is excluded explicitly so its otherwise
    identical ``대여한다`` suffix cannot be clicked by mistake.
    """
    for text, box in lines:
        compact = "".join(text.split())
        if "대여한다" in compact and "홀" not in compact:
            return box
    return None


def _build_dialog_content_locator(settings: dict, project_root: Path) -> WindowContentLocator:
    dialog_cfg = settings["dialog"]
    border = SkillPanelLocator(project_root / dialog_cfg["template"], dialog_cfg.get("match_threshold", 0.85))
    return WindowContentLocator(border, ContentOffset(**dialog_cfg["content_offset"]))


def build_hotel_text_locator(settings: dict, project_root: Path, reader: KoreanTextReader) -> RememberedDialogText:
    # Yellow-masked before OCR -- "[오렌] 여관" renders in yellow in this
    # dialog, same speedup/accuracy reasoning as
    # step_move_to_wasteland.py's post-gate dialogs (see
    # mask_non_yellow()'s docstring).
    return RememberedDialogText(
        _build_dialog_content_locator(settings, project_root),
        reader,
        first_matching(needles_match_fn(*HOTEL_NEEDLES)),
        preprocess=mask_non_yellow,
        merge_rows=True,
    )


def build_rent_room_text_locator(settings: dict, project_root: Path, reader: KoreanTextReader) -> RememberedDialogText:
    # Yellow-masked before OCR -- "방을 대여한다" renders in yellow in
    # this NPC-menu dialog, same reasoning as build_hotel_text_locator()
    # above.
    return RememberedDialogText(
        _build_dialog_content_locator(settings, project_root),
        reader,
        _select_rent_room,
        preprocess=mask_non_yellow,
    )


def build_ok_button_text_locator(settings: dict, project_root: Path, reader: KoreanTextReader) -> RememberedDialogText:
    # The OK label is black, not yellow. Keep the original dialog crop
    # for OCR and explicitly avoid mask_non_yellow().
    return RememberedDialogText(
        _build_dialog_content_locator(settings, project_root),
        reader,
        first_matching(needles_match_fn(*OK_NEEDLES)),
        preprocess=None,
    )


def build_talking_scroll_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["talking_scroll"], project_root, panel=skill_panel)


def locate_talking_scroll(settings: dict, project_root: Path, frame: np.ndarray, skill_panel: SkillPanelLocator) -> PresenceResult:
    return build_talking_scroll_detector(settings, project_root, skill_panel).measure(frame)


def locate_hotel_manager(settings: dict, project_root: Path, frame: np.ndarray):
    """Plain unscoped template match for npc_hotel_manager.png -- a
    world-space NPC sprite, not a UI icon, so no panel to scope the
    search to (see module docstring). Returns a
    template_locator.MatchResult or None."""
    npc_cfg = settings["npcs"]["hotel_manager"]
    template = cv2.imread(str(project_root / npc_cfg["template"]))
    return locate_template(frame, template, npc_cfg.get("match_threshold", 0.85))


def run(settings: dict, project_root: Path, window_title: str, link: SerialLink, skill_panel: SkillPanelLocator,
        hotel_text: RememberedDialogText, rent_room_text: RememberedDialogText, ok_button_text: RememberedDialogText,
        screen_capture_cls) -> bool:
    """Full [1단계]: the 5 sub-actions from the module docstring, as a
    reusable function (for pc/routine/run_all.py) instead of a script
    entry point. Takes pre-built RememberedDialogText locators so their
    OCR caches persist across repeated calls in a long-running loop
    instead of resetting every process invocation. Returns False as
    soon as any sub-action fails to find its target or ACK."""
    print("[1/5] talking_scroll: pressing F2...")
    if not ensure_skill_tab(link):
        print("[stop] F2 keypress not ACKed")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    print("  parking cursor (clear any leftover tooltip from a previous step)...")
    park_cursor(link, converter)
    sleep_jittered(0.2)
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    scroll = locate_talking_scroll(settings, project_root, frame, skill_panel)
    print(f"  talking_scroll: present={scroll.present} score={scroll.match_score:.3f} region={scroll.region}")
    if not scroll.present:
        print("[stop] talking_scroll not present.")
        return False
    ok = double_click_region(link, converter, scroll.region)
    print(f"  double-click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {DIALOG_OPEN_SETTLE_S}s for dialog...")
    sleep_jittered(DIALOG_OPEN_SETTLE_S)

    print("[2/5] finding '[오렌] 여관' text...")
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    hotel_target = hotel_text.find(frame)
    print(f"  target region: {hotel_target}")
    if hotel_target is None:
        print("[stop] '오렌'+'여관' text not found -- is the dialog open?")
        return False
    ok = click_region_once(link, converter, hotel_target)
    print(f"  click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {TELEPORT_SETTLE_S}s for teleport...")
    sleep_jittered(TELEPORT_SETTLE_S)

    print("[3/5] finding npc_hotel_manager...")
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    npc_match = locate_hotel_manager(settings, project_root, frame)
    if npc_match is None:
        npc_cfg = settings["npcs"]["hotel_manager"]
        template = cv2.imread(str(project_root / npc_cfg["template"]))
        best = locate_template(frame, template, 0.0)
        print(f"  [stop] no match >= threshold (best score below threshold: {best.score:.3f} @ {best.region})")
        return False
    print(f"  hotel_manager: region={npc_match.region} score={npc_match.score:.3f}")
    ok = click_region_once(link, converter, npc_match.region, jitter=SPRITE_CLICK_JITTER)
    print(f"  click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {DIALOG_STEP_SETTLE_S}s for NPC dialogue...")
    sleep_jittered(DIALOG_STEP_SETTLE_S)

    print("[4/5] finding '방을 대여한다' text...")
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    rent_target = rent_room_text.find(frame)
    print(f"  target region: {rent_target}")
    if rent_target is None:
        # Confirmed live: the NPC dialogue can still be rendering at this
        # point (click landed fine, score 0.990, but the dialogue text
        # wasn't up yet) -- one extra wait-and-retry before giving up,
        # rather than failing on what's just slow rendering.
        print(f"  not found -- retrying once after another {DIALOG_STEP_SETTLE_S}s...")
        sleep_jittered(DIALOG_STEP_SETTLE_S)
        frame, converter = _capture_and_convert(window_title, screen_capture_cls)
        rent_target = rent_room_text.find(frame)
        print(f"  target region (retry): {rent_target}")
    if rent_target is None:
        print("[stop] '방을'+'대여한다' text not found -- is NPC dialogue open?")
        return False
    ok = click_region_once(link, converter, rent_target)
    print(f"  click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {DIALOG_STEP_SETTLE_S}s for the confirm prompt...")
    sleep_jittered(DIALOG_STEP_SETTLE_S)

    print("[5/5] finding 'OK' button...")
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    ok_target = ok_button_text.find(frame)
    print(f"  target region: {ok_target}")
    if ok_target is None:
        print("[stop] 'OK' text not found -- is the confirm prompt open?")
        return False
    ok = click_region_once(link, converter, ok_target)
    print(f"  click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    sleep_jittered(0.6)
    return ok


def main() -> None:
    from pc.config.config_loader import load_settings
    from pc.capture.screen_capture import ScreenCapture
    from pc.capture.window_locator import WindowNotFoundError
    from pc.serial.port_finder import resolve_port

    settings = load_settings()
    window_title = settings["capture"]["window_title"]

    roi_skill_cfg = settings["roi_skill"]
    skill_panel = SkillPanelLocator(
        _PROJECT_ROOT / roi_skill_cfg["template"], roi_skill_cfg["match_threshold"],
        roi_skill_cfg.get("search_region"),
    )

    print("Loading Korean OCR model...")
    reader = KoreanTextReader()
    hotel_text = build_hotel_text_locator(settings, _PROJECT_ROOT, reader)
    rent_room_text = build_rent_room_text_locator(settings, _PROJECT_ROOT, reader)
    ok_button_text = build_ok_button_text_locator(settings, _PROJECT_ROOT, reader)

    serial_cfg = settings["serial"]
    try:
        with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
            sleep_jittered(2.5)  # Leonardo boot delay after port open
            link.send("PING")
            sleep_jittered(0.3)
            link.poll_acks()

            ok = run(settings, _PROJECT_ROOT, window_title, link, skill_panel,
                     hotel_text, rent_room_text, ok_button_text, ScreenCapture)
            if not ok:
                sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)

    OUTPUT_DIR = _PROJECT_ROOT / "output"
    OUTPUT_DIR.mkdir(exist_ok=True)
    with ScreenCapture(window_title=window_title) as cap:
        after = cap.grab()
    out_path = OUTPUT_DIR / "step_buy_hotel_key_result.png"
    cv2.imwrite(str(out_path), after)
    print(f"Screenshot saved -> {out_path}")


if __name__ == "__main__":
    main()
