"""[3단계] 버려진땅 이동.

1. roi_skill에서 icon_teleport_scroll 더블클릭 -> 텔레포트 목록 대화창(dialog) 오픈
2. dialog 영역에서 "* [오렌] 버땅" 텍스트를 더블클릭
3. npc_teleport_gate 이미지와 가장 비슷한 부분(월드 공간, 화면 전체 검색)을 원클릭
4. 3번이 여는 새 dialog(같은 generic dialog 프레임, 다른 내용)에서 "버림받은 자들의
   땅" 텍스트의 랜덤한 부분을 원클릭
5. 4번이 여는 세 번째 dialog(레벨 제한 안내 + 최종 진입 확인)에서 "발을 내딛는다"
   텍스트를 원클릭
6. 실제로 "버림받은 자들의 땅"으로 위치가 바뀌었는지 확인
   (location anchor + fixed-label template matching).
   실기에서 5번 클릭이 ACK는 성공해도 실제로 텔레포트가 안 되는 경우가 확인돼서
   추가함 -- 확인 안 되면 "발을 내딛는다"를 다시 찾아 재클릭한다
   (`location.verify_timeout_seconds` 동안 재확인).

icon_teleport_scroll도 hotel_key/meditation과 같은 F2 quick-slot 탭에 있으므로
step_move_to_hotel의 ensure_skill_tab()/double_click_region()을 그대로 재사용한다.

sub-action 3은 아이콘이 아니라 게임 월드에 렌더링되는 오브젝트라서 roi_skill 같은
패널에 스코프하지 않고 프레임 전체를 대상으로 template matching한다 (npc_hotel_manager
때와 동일한 이유 -- 이름표 텍스트가 아니라 스프라이트 자체를 클릭해야 상호작용됨).

세 텍스트 찾기(2, 4, 5번)는 전부 RememberedDialogText를 통해서 한다 -- 서로 다른
dialog 내용이라 인스턴스도 각각 별개(캐시 공유 안 함). OCR은 인스턴스당 최초 1회만
돌고, 그 뒤로는 위치를 기억해서 dialog anchor(OCR 아닌, 싼 템플릿 매칭)만 다시
맞춰 클릭한다. 같은 dialog를 여러 번 여닫는 실제 반복 루틴에서 OCR 비용을 없애기
위함 -- pc/detector/remembered_text.py 참고.

4번은 "버림받은 자들의 땅:심연"이라는 형제 항목이 같은 dialog에 같이 있어서 원래는
공백 제거 후 완전 일치(exact_match_fn)로 걸렀는데, 실기 테스트에서 PaddleOCR이
"버림받은 자들의 땅"(형제 없는 쪽) 줄의 "자들의 땅" 부분만 종종 통째로 오인식하는
걸 발견했다 (같은 스크린샷에서 형제 줄 "버림받은 자들의 땅:심연"은 멀쩡히 읽힘) --
그래서 완전 일치 자체가 실패한다. _select_wasteland_gate_destination()은 그 대신
"버림받은"이 들어간 줄들 중 근처(세로로 가까운 위치)에 "심연"이 있는 줄을 제외하는
방식으로 고른다 -- "자들의 땅" 부분이 정확히 뭐라고 인식됐는지와 무관하게 동작한다.

3번(게이트 클릭)은 재시도 로직이 있다 -- 게이트가 열린 필드 한복판에 있다 보니
몬스터가 그 위에 겹쳐서(또는 겹치게 이동해서) 클릭이 게이트 대신 몬스터에 맞는
경우가 실기로 확인됐다. 미리 막을 몬스터 감지기는 없어서, 대신 클릭 직후 4번의
목적지 dialog가 실제로 열렸는지 확인하고 안 열렸으면 게이트를 다시 찾아 재클릭한다
(GATE_CLICK_MAX_ATTEMPTS). 알려진 한계: 몬스터를 잘못 클릭하면 어그로가 끌릴 수
있는데, 이 재시도는 그걸 먼저 해제하려 하지 않고 그냥 게이트를 다시 클릭한다.

All mouse movement/clicking goes through the Arduino (SerialLink), never
a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.capture.screen_capture import Region  # noqa: E402
from pc.detector.any_presence_detector import AnyPresenceDetector, build_icon_detector  # noqa: E402
from pc.detector.presence_detector import PresenceResult  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.window_content import ContentOffset, WindowContentLocator  # noqa: E402
from pc.detector.chat_reader import KoreanTextReader, needles_match_fn  # noqa: E402
from pc.detector.remembered_text import RememberedDialogText, first_matching  # noqa: E402
from pc.detector.color_mask import mask_non_yellow  # noqa: E402
from pc.detector.template_locator import MatchResult, locate_template  # noqa: E402
from pc.action.frame_to_mouse import FrameToMouseConverter  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.routine.step_move_to_hotel import ensure_skill_tab, double_click_region, park_cursor, _capture_and_convert  # noqa: E402

# How long to wait after double-clicking teleport_scroll before the
# dialog has finished opening/rendering.
DIALOG_OPEN_SETTLE_S = 0.6

# How long to wait after clicking the destination text before the
# teleport gate has finished rendering in the world.
GATE_RENDER_SETTLE_S = 0.8

WASTELAND_NEEDLES = ("오렌", "버땅")
STEP_FORWARD_NEEDLES = ("발을", "내딛는다")

GATE_DESTINATION_NEEDLE = "버림받은"
GATE_SIBLING_NEEDLE = "심연"
# Two menu rows in the same dialog are close together (~19-23px tall
# each here) -- this just needs to be smaller than the gap *between*
# rows so it doesn't accidentally associate a "심연" box with the wrong
# row above/below it.
GATE_ROW_Y_TOLERANCE = 20

# Confirmed live: the "발을 내딛는다" click can ACK fine (the Arduino did
# physically click) without actually teleporting the character -- same
# false-success pattern as meditation in step_move_to_hotel.py. Instead
# of trusting the ACK, re-check the character's actual location via
# `location`'s anchor+offset and target template (see settings.yaml),
# and retry the click if it doesn't show the wasteland yet.
def _select_wasteland_gate_destination(lines: List[Tuple[str, Region]]) -> Optional[Region]:
    """"버림받은 자들의 땅" (not its "...: 심연" sibling) inside the
    npc_teleport_gate confirm dialog. Picks the box containing "버림받은"
    that does NOT have a "심연" box near it vertically -- see module
    docstring for why this doesn't just match/exclude the full string."""
    def compact(text: str) -> str:
        return re.sub(r"\s+", "", text)

    def row_center(box: Region) -> float:
        return box.top + box.height / 2

    simyeon_centers = [row_center(box) for text, box in lines if GATE_SIBLING_NEEDLE in compact(text)]
    for text, box in lines:
        if GATE_DESTINATION_NEEDLE not in compact(text):
            continue
        center = row_center(box)
        if any(abs(center - sc) < GATE_ROW_Y_TOLERANCE for sc in simyeon_centers):
            continue
        return box
    return None


def _build_dialog_content_locator(settings: dict, project_root: Path) -> WindowContentLocator:
    dialog_cfg = settings["dialog"]
    border = SkillPanelLocator(project_root / dialog_cfg["template"], dialog_cfg.get("match_threshold", 0.85))
    return WindowContentLocator(border, ContentOffset(**dialog_cfg["content_offset"]))


def build_location_content_locator(settings: dict, project_root: Path) -> WindowContentLocator:
    """`location`'s anchor (the static stat-panel icon right below where
    the location name renders, see settings.yaml) + fixed offset -- only
    visible outdoors, blank indoors/in the hotel room."""
    loc_cfg = settings["location"]
    anchor = SkillPanelLocator(project_root / loc_cfg["template"], loc_cfg.get("match_threshold", 0.75))
    return WindowContentLocator(anchor, ContentOffset(**loc_cfg["content_offset"]))


@dataclass
class LocationTemplateVerifier:
    template: np.ndarray
    threshold: float

    @staticmethod
    def _text_mask(image: np.ndarray) -> np.ndarray:
        """Keep the pink/red location-label pixels and discard terrain.

        The label is fixed but the transparent UI background changes
        with the terrain (dark grass, bright snow, etc.). Matching this
        mask makes the verifier depend on the glyphs rather than the
        world behind them.
        """
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        red_low = cv2.inRange(hsv, (0, 35, 100), (18, 255, 255))
        red_high = cv2.inRange(hsv, (165, 35, 100), (179, 255, 255))
        return cv2.bitwise_or(red_low, red_high)

    def measure(self, crop: np.ndarray) -> PresenceResult:
        """Return the real best score even when it is below threshold."""
        th, tw = self.template.shape[:2]
        ch, cw = crop.shape[:2]
        if ch < th or cw < tw:
            return PresenceResult(present=False, region=None, match_score=0.0)
        result = cv2.matchTemplate(
            self._text_mask(crop), self._text_mask(self.template), cv2.TM_CCOEFF_NORMED
        )
        _, max_score, _, max_loc = cv2.minMaxLoc(result)
        region = Region(left=max_loc[0], top=max_loc[1], width=tw, height=th)
        return PresenceResult(
            present=max_score >= self.threshold,
            region=region,
            match_score=float(max_score),
        )


def build_wasteland_location_detector(settings: dict, project_root: Path) -> LocationTemplateVerifier:
    """Build the fixed-label verifier used after teleporting.

    The location label is a tiny outlined game font. The Korean OCR
    model consistently misreads this otherwise correctly cropped text,
    so exact-location verification uses a dedicated visual template.
    """
    loc_cfg = settings["location"]
    template_path = project_root / loc_cfg["target_template"]
    template = cv2.imread(str(template_path))
    if template is None:
        raise FileNotFoundError(f"Could not load location template image: {template_path}")
    return LocationTemplateVerifier(template, float(loc_cfg.get("target_match_threshold", 0.8)))


def measure_wasteland_location(content_locator: WindowContentLocator,
                               detector: LocationTemplateVerifier,
                               frame: np.ndarray) -> PresenceResult:
    crop = content_locator.crop_content(frame)
    if crop is None:
        return PresenceResult(present=False, region=None, match_score=0.0)
    return detector.measure(crop)


def save_gate_preclick_frame(frame: np.ndarray, output_dir: Path, attempt: int,
                             gate_match: MatchResult) -> Optional[Path]:
    """Save the raw game-client frame immediately before a gate click.

    Coordinates and match score are kept in the filename so a later
    false-positive analysis can associate the screenshot with the log.
    A debug-write failure must not interfere with the live routine.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_ms = int(time.time() * 1000)
        region = gate_match.region
        score = int(round(gate_match.score * 1000))
        path = output_dir / (
            f"gate_preclick_{timestamp_ms}_attempt{attempt:02d}_"
            f"score{score:04d}_x{region.left}_y{region.top}.png"
        )
        if not cv2.imwrite(str(path), frame):
            return None
        return path
    except (OSError, cv2.error):
        return None


def save_gate_failure_frame(frame: np.ndarray, output_dir: Path, attempt: int,
                            best_match: MatchResult) -> Optional[Path]:
    """Save the full game-client frame when no gate reaches threshold."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp_ms = int(time.time() * 1000)
        region = best_match.region
        score = int(round(best_match.score * 1000))
        path = output_dir / (
            f"gate_not_found_{timestamp_ms}_attempt{attempt:02d}_"
            f"bestscore{score:04d}_x{region.left}_y{region.top}.png"
        )
        if not cv2.imwrite(str(path), frame):
            return None
        return path
    except (OSError, cv2.error):
        return None


def build_wasteland_text_locator(settings: dict, project_root: Path, reader: KoreanTextReader) -> RememberedDialogText:
    """"* [오렌] 버땅" inside the icon_teleport_scroll dialog."""
    content_locator = _build_dialog_content_locator(settings, project_root)
    return RememberedDialogText(content_locator, reader, first_matching(needles_match_fn(*WASTELAND_NEEDLES)))


def build_gate_destination_text_locator(settings: dict, project_root: Path, reader: KoreanTextReader) -> RememberedDialogText:
    """"버림받은 자들의 땅" (not the "...: 심연" sibling) inside the
    npc_teleport_gate confirm dialog -- a different dialog
    instance/content than icon_teleport_scroll's, but the same generic
    `dialog` border/content_offset applies. Both this dialog and the one
    build_step_forward_text_locator() reads render their action text in
    yellow against an otherwise-white-text lore paragraph, so both mask
    to yellow-only before OCR -- ~10x faster (measured 7810ms ->
    805ms) and, as a side effect, fixed the "자들의 땅" misrecognition
    documented above (see mask_non_yellow()'s docstring for why). Not
    applied to the icon_teleport_scroll dialog's plain-white list
    (build_wasteland_text_locator) or the NPC-menu/OK dialogs in
    step_buy_hotel_key.py -- their target text isn't yellow.

    cache=False: this follows a low-confidence npc_teleport_gate click
    (a template match that can land on a false positive -- confirmed
    live). A stale dialog left over from an
    earlier step can still satisfy the generic border-anchor match, so
    trusting a cached offset here risks reporting "found" against the
    wrong dialog entirely instead of correctly reporting "not found".
    See RememberedDialogText's docstring."""
    content_locator = _build_dialog_content_locator(settings, project_root)
    return RememberedDialogText(content_locator, reader, _select_wasteland_gate_destination, preprocess=mask_non_yellow, cache=False)


def build_step_forward_text_locator(settings: dict, project_root: Path, reader: KoreanTextReader) -> RememberedDialogText:
    """"발을 내딛는다" inside the third dialog (level-requirement notice +
    final entry confirmation) that picking "버림받은 자들의 땅" opens --
    a different dialog instance/content again, but the same generic
    `dialog` border/content_offset applies. Yellow-masked before OCR,
    same reasoning as build_gate_destination_text_locator() above --
    and cache=False for the same reason too (follows the same
    low-confidence gate click)."""
    content_locator = _build_dialog_content_locator(settings, project_root)
    return RememberedDialogText(content_locator, reader, first_matching(needles_match_fn(*STEP_FORWARD_NEEDLES)), preprocess=mask_non_yellow, cache=False)


def build_teleport_scroll_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["teleport_scroll"], project_root, panel=skill_panel)


def locate_teleport_scroll(settings: dict, project_root: Path, frame: np.ndarray, skill_panel: SkillPanelLocator) -> PresenceResult:
    return build_teleport_scroll_detector(settings, project_root, skill_panel).measure(frame)


def open_teleport_dialog(link: SerialLink, converter: FrameToMouseConverter, icon_region: Region) -> bool:
    return double_click_region(link, converter, icon_region)


def _partial_gate_match(frame: np.ndarray, template: np.ndarray, threshold: float,
                        min_visible_fraction: float, scan_step_px: int) -> Optional[MatchResult]:
    """Match the visible part of a gate clipped by a frame edge.

    Partial templates are compared only flush against the corresponding
    screen edge.  This avoids accepting an arbitrary fragment in the
    middle of the game world.  The returned region is only the visible
    intersection, so its center is always a valid click coordinate.
    """
    fh, fw = frame.shape[:2]
    th, tw = template.shape[:2]
    min_h = max(2, int(round(th * min_visible_fraction)))
    min_w = max(2, int(round(tw * min_visible_fraction)))
    step = max(1, scan_step_px)
    candidates: List[MatchResult] = []

    def remember(image: np.ndarray, needle: np.ndarray, left_offset: int, top_offset: int) -> None:
        ih, iw = image.shape[:2]
        nh, nw = needle.shape[:2]
        if ih < nh or iw < nw:
            return
        result = cv2.matchTemplate(image, needle, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score >= threshold:
            candidates.append(MatchResult(
                region=Region(left=left_offset + location[0], top=top_offset + location[1],
                              width=nw, height=nh),
                score=float(score),
            ))

    visible_heights = list(range(min_h, min(th, fh), step))
    visible_widths = list(range(min_w, min(tw, fw), step))

    # Gate extends beyond the top or bottom edge; horizontal position is unknown.
    for visible_h in visible_heights:
        remember(frame[:visible_h, :], template[th - visible_h:, :], 0, 0)
        remember(frame[fh - visible_h:, :], template[:visible_h, :], 0, fh - visible_h)

    # Gate extends beyond the left or right edge; vertical position is unknown.
    for visible_w in visible_widths:
        remember(frame[:, :visible_w], template[:, tw - visible_w:], 0, 0)
        remember(frame[:, fw - visible_w:], template[:, :visible_w], fw - visible_w, 0)

    if candidates:
        return max(candidates, key=lambda match: match.score)

    # A gate can be clipped by two edges at a corner. Coarser combinations
    # keep this fallback inexpensive while still covering varying exposure.
    corner_step = max(step, 4)
    for visible_h in range(min_h, min(th, fh), corner_step):
        for visible_w in range(min_w, min(tw, fw), corner_step):
            corner_specs = (
                (frame[:visible_h, :visible_w], template[th - visible_h:, tw - visible_w:], 0, 0),
                (frame[:visible_h, fw - visible_w:], template[th - visible_h:, :visible_w], fw - visible_w, 0),
                (frame[fh - visible_h:, :visible_w], template[:visible_h, tw - visible_w:], 0, fh - visible_h),
                (frame[fh - visible_h:, fw - visible_w:], template[:visible_h, :visible_w], fw - visible_w, fh - visible_h),
            )
            for image, needle, left, top in corner_specs:
                remember(image, needle, left, top)

    return max(candidates, key=lambda match: match.score, default=None)


def locate_teleport_gate(settings: dict, project_root: Path, frame: np.ndarray):
    """Find a full gate, then fall back to a gate clipped by a frame edge."""
    gate_cfg = settings["npcs"]["teleport_gate"]
    template = cv2.imread(str(project_root / gate_cfg["template"]))
    if template is None:
        raise FileNotFoundError(f"Could not load gate template: {project_root / gate_cfg['template']}")

    full_match = locate_template(frame, template, gate_cfg.get("match_threshold", 0.85))
    if full_match is not None:
        return full_match

    return _partial_gate_match(
        frame,
        template,
        float(gate_cfg.get("partial_match_threshold", 0.5)),
        float(gate_cfg.get("partial_min_visible_fraction", 0.5)),
        int(gate_cfg.get("partial_scan_step_px", 2)),
    )


# npc_teleport_gate sits out in the open world, where a monster can walk
# in front of it (or spawn on top of it) between the moment we locate it
# and the moment the click lands -- confirmed live: the click landed on
# a monster standing over the gate instead, so no destination dialog
# opened. There's no monster detector in this project to check for that
# in advance, so instead of trying to prevent it, this retries: after
# each click, verify the destination dialog actually opened (that's
# what gate_dest_text.find() below is for) -- if not, assume the click
# missed the gate and just try again with a fresh frame (the monster
# may have moved on by then). Retries deliberately do not move the
# character because that changes the scene and can obstruct detection.
GATE_CLICK_MAX_ATTEMPTS = 5
GATE_RETRY_INTERVAL_S = 0.5

# OCR text boxes are clicked at their exact center. NPC/object sprite
# regions (npc_hotel_manager, npc_teleport_gate) still use a small
# explicit random range because the template
# crop's bounding box often includes background margin around the
# actual silhouette (counter, floor, snow...), so a wide-range random
# click can land off the character/object entirely and silently miss
# the interaction -- confirmed live (NPC dialogue repeatedly failed to
# open; the click had landed just outside the sprite). Use
# SPRITE_CLICK_JITTER for those instead.
TEXT_CLICK_JITTER = 0.0
SPRITE_CLICK_JITTER = 0.1


def _step3_hp_is_critical(frame: np.ndarray, hp_detector, threshold_percent: float) -> bool:
    if hp_detector is None:
        return False
    result = hp_detector.measure(frame)
    if result is None:
        print("  [3단계 HP] unreadable -- continuing this checkpoint")
        return False
    hp = result.reading
    print(f"  [3단계 HP] {hp.current}/{hp.maximum} ({hp.percent:.1f}%)")
    if hp.percent <= threshold_percent:
        print(f"  [3단계 HP] <= {threshold_percent:.0f}% -- handoff to [2단계]")
        return True
    return False


def click_region_once(link: SerialLink, converter: FrameToMouseConverter, region: Region, jitter: float = TEXT_CLICK_JITTER) -> bool:
    fx = region.left + region.width * (0.5 + random.uniform(-jitter, jitter))
    fy = region.top + region.height * (0.5 + random.uniform(-jitter, jitter))
    ux, uy = converter.convert(fx, fy)

    move_ack = link.send_and_wait("MOUSE_MOVE", f"{ux} {uy}")
    if move_ack is None or not move_ack.ok:
        return False
    time.sleep(0.15)
    click_ack = link.send_and_wait("MOUSE_CLICK", "LEFT")
    if click_ack is None or not click_ack.ok:
        return False
    time.sleep(0.1)
    park_cursor(link, converter)
    return True


def double_click_text_center(link: SerialLink, converter: FrameToMouseConverter,
                             region: Region) -> bool:
    """Double-click the exact center of an OCR-recognized text box."""
    fx = region.left + region.width * 0.5
    fy = region.top + region.height * 0.5
    ux, uy = converter.convert(fx, fy)

    move_ack = link.send_and_wait("MOUSE_MOVE", f"{ux} {uy}")
    if move_ack is None or not move_ack.ok:
        return False
    time.sleep(0.15)
    click1 = link.send_and_wait("MOUSE_CLICK", "LEFT")
    if click1 is None or not click1.ok:
        return False
    time.sleep(0.12)
    click2 = link.send_and_wait("MOUSE_CLICK", "LEFT")
    if click2 is None or not click2.ok:
        return False
    time.sleep(0.1)
    park_cursor(link, converter)
    return True


def run(settings: dict, project_root: Path, window_title: str, link: SerialLink, skill_panel: SkillPanelLocator,
        wasteland_text: RememberedDialogText, gate_dest_text: RememberedDialogText, step_forward_text: RememberedDialogText,
        reader: KoreanTextReader, screen_capture_cls, hp_detector=None) -> Optional[bool]:
    """Full [3단계]: the 5 sub-actions from the module docstring plus a
    final location check, as a reusable function (for
    pc/routine/run_all.py) instead of a script entry point. Takes
    pre-built RememberedDialogText locators so their OCR caches persist
    across repeated calls in a long-running loop instead of resetting
    every process invocation. Returns None when recovery through
    [2단계] is needed (critical HP or all gate attempts exhausted), and
    False when another sub-action fails or the location never confirms."""
    hp_exit_percent = float(settings.get("step3", {}).get("hp_exit_percent", 30.0))
    print("[1/6] teleport_scroll: pressing F2...")
    if not ensure_skill_tab(link):
        print("[stop] F2 keypress not ACKed")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    print("  parking cursor (clear any leftover tooltip from a previous step)...")
    park_cursor(link, converter)
    time.sleep(0.2)
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    if _step3_hp_is_critical(frame, hp_detector, hp_exit_percent):
        return None
    scroll = locate_teleport_scroll(settings, project_root, frame, skill_panel)
    print(f"  teleport_scroll: present={scroll.present} score={scroll.match_score:.3f} region={scroll.region}")
    if not scroll.present:
        print("[stop] teleport_scroll not present.")
        return False
    ok = open_teleport_dialog(link, converter, scroll.region)
    print(f"  double-click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {DIALOG_OPEN_SETTLE_S}s for dialog...")
    time.sleep(DIALOG_OPEN_SETTLE_S)

    print("[2/6] finding '* [오렌] 버땅' text...")
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    if _step3_hp_is_critical(frame, hp_detector, hp_exit_percent):
        return None
    target = wasteland_text.find(frame)
    print(f"  target region: {target}")
    if target is None:
        print("[stop] '오렌'+'버땅' text not found -- is the dialog open?")
        return False
    ok = double_click_text_center(link, converter, target)
    print(f"  double-click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {GATE_RENDER_SETTLE_S}s for the teleport gate to render...")
    time.sleep(GATE_RENDER_SETTLE_S)

    print("[3/6] finding npc_teleport_gate (with retry-on-miss)...")
    dest_target = None
    for attempt in range(1, GATE_CLICK_MAX_ATTEMPTS + 1):
        frame, converter = _capture_and_convert(window_title, screen_capture_cls)
        if _step3_hp_is_critical(frame, hp_detector, hp_exit_percent):
            return None
        gate_match = locate_teleport_gate(settings, project_root, frame)
        if gate_match is None:
            # Also print the best score even below threshold, for
            # calibrating match_threshold live. Treated the same
            # as "clicked but destination dialog didn't open"
            # below -- a monster standing squarely on the gate
            # can occlude enough of it to drop the match below
            # threshold entirely, not just cause a miss-click, so
            # retreat-and-retry applies here too.
            gate_cfg = settings["npcs"]["teleport_gate"]
            template = cv2.imread(str(project_root / gate_cfg["template"]))
            best = locate_template(frame, template, -1.0)
            print(f"  attempt {attempt}/{GATE_CLICK_MAX_ATTEMPTS}: no match >= threshold (best score below threshold: {best.score:.3f} @ {best.region})")
            failure_path = save_gate_failure_frame(
                frame, project_root / "output" / "gate_failures", attempt, best
            )
            if failure_path is not None:
                print(f"    saved gate-failure game frame: {failure_path}")
            else:
                print("    [warn] failed to save gate-failure game frame")
        else:
            gate_cfg = settings["npcs"]["teleport_gate"]
            gate_template = cv2.imread(str(project_root / gate_cfg["template"]))
            is_partial = (
                gate_template is not None
                and (gate_match.region.width < gate_template.shape[1]
                     or gate_match.region.height < gate_template.shape[0])
            )
            match_kind = "partial edge match" if is_partial else "full match"
            print(f"  attempt {attempt}/{GATE_CLICK_MAX_ATTEMPTS}: teleport_gate region={gate_match.region} score={gate_match.score:.3f} ({match_kind})")
            debug_path = save_gate_preclick_frame(
                frame, project_root / "output" / "gate_preclick", attempt, gate_match
            )
            if debug_path is not None:
                print(f"    saved pre-click game frame: {debug_path}")
            else:
                print("    [warn] failed to save pre-click game frame")
            ok = click_region_once(link, converter, gate_match.region, jitter=SPRITE_CLICK_JITTER)
            print(f"    click -> {'ok' if ok else 'FAILED (missing ACK)'}")
            if not ok:
                return False

            print(f"    waiting {DIALOG_OPEN_SETTLE_S}s for the destination dialog...")
            time.sleep(DIALOG_OPEN_SETTLE_S)

            frame, converter = _capture_and_convert(window_title, screen_capture_cls)
            if _step3_hp_is_critical(frame, hp_detector, hp_exit_percent):
                return None
            dest_target = gate_dest_text.find(frame)
            if dest_target is not None:
                print(f"    destination dialog found: {dest_target}")
                break
            print("    '버림받은 자들의 땅' not found -- click likely missed the gate (e.g. a monster overlapping it)")

        if attempt < GATE_CLICK_MAX_ATTEMPTS:
            print(f"    waiting {GATE_RETRY_INTERVAL_S}s before stationary retry...")
            time.sleep(GATE_RETRY_INTERVAL_S)

    print("[4/6] clicking '버림받은 자들의 땅' (exact, not '...심연')...")
    if dest_target is None:
        print(f"[3단계] gate not found/opened after {GATE_CLICK_MAX_ATTEMPTS} attempts -- handoff to [2단계]")
        return None
    ok = click_region_once(link, converter, dest_target)
    print(f"  click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print(f"Waiting {DIALOG_OPEN_SETTLE_S}s for the level-requirement/confirm dialog...")
    time.sleep(DIALOG_OPEN_SETTLE_S)

    print("[5/6] finding '발을 내딛는다' text...")
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    if _step3_hp_is_critical(frame, hp_detector, hp_exit_percent):
        return None
    forward_target = step_forward_text.find(frame)
    print(f"  target region: {forward_target}")
    if forward_target is None:
        print("[stop] '발을'+'내딛는다' text not found -- is the confirm dialog open?")
        return False
    ok = click_region_once(link, converter, forward_target)
    print(f"  click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    if not ok:
        return False

    print("[6/6] verifying location changed to '버림받은 자들의 땅'...")
    location_content_locator = build_location_content_locator(settings, project_root)
    location_detector = build_wasteland_location_detector(settings, project_root)
    location_cfg = settings["location"]
    verify_timeout_s = float(location_cfg.get("verify_timeout_seconds", 6.0))
    verify_interval_s = float(location_cfg.get("verify_interval_seconds", 0.5))
    deadline = time.monotonic() + verify_timeout_s
    attempt = 0
    retried_click = False
    while time.monotonic() < deadline:
        time.sleep(verify_interval_s)
        attempt += 1
        frame, converter = _capture_and_convert(window_title, screen_capture_cls)
        if _step3_hp_is_critical(frame, hp_detector, hp_exit_percent):
            return None
        location_result = measure_wasteland_location(location_content_locator, location_detector, frame)
        print(f"  location check {attempt}: present={location_result.present} score={location_result.match_score:.3f}")
        if location_result.present:
            print("  location confirmed -- [3단계] complete")
            return True
        # If the confirmation dialog is still visible, the previous HID
        # click did not take effect. Retry it once, then keep polling the
        # actual location until the timeout instead of assuming a fixed
        # transition time.
        if not retried_click:
            retry_target = step_forward_text.find(frame)
            if retry_target is not None:
                print("  location not confirmed -- '발을 내딛는다' still there, retrying click...")
                retry_ok = click_region_once(link, converter, retry_target)
                print(f"    retry click -> {'ok' if retry_ok else 'FAILED (missing ACK)'}")
                retried_click = True

    print(f"[stop] location never confirmed as '버림받은 자들의 땅' within {verify_timeout_s:.1f}s.")
    return False


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
    wasteland_text = build_wasteland_text_locator(settings, _PROJECT_ROOT, reader)
    gate_dest_text = build_gate_destination_text_locator(settings, _PROJECT_ROOT, reader)
    step_forward_text = build_step_forward_text_locator(settings, _PROJECT_ROOT, reader)

    serial_cfg = settings["serial"]
    try:
        with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
            time.sleep(2.5)  # Leonardo boot delay after port open
            link.send("PING")
            time.sleep(0.3)
            link.poll_acks()

            ok = run(settings, _PROJECT_ROOT, window_title, link, skill_panel,
                     wasteland_text, gate_dest_text, step_forward_text, reader, ScreenCapture)
            if not ok:
                sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)

    OUTPUT_DIR = _PROJECT_ROOT / "output"
    OUTPUT_DIR.mkdir(exist_ok=True)
    with ScreenCapture(window_title=window_title) as cap:
        after = cap.grab()
    out_path = OUTPUT_DIR / "step_move_to_wasteland_result.png"
    cv2.imwrite(str(out_path), after)
    print(f"Screenshot saved -> {out_path}")


if __name__ == "__main__":
    main()
