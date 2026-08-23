"""[4단계] ATS ON + 자동 텔 사냥 모니터링.

[3단계](step_move_to_wasteland.py) 완료 후 실행한다.

1. icon_ats_off를 더블클릭 -> icon_ats_on 상태로 토글.
2. 그 뒤 1초 간격으로 HP/MP를 계속 읽으면서:
   - HP <= 70%가 2틱 연속 확인되면 F9 키를 두 번 입력하고, HP가 70%를
     초과할 때까지 매 감시 주기마다 반복한다.
   - HP <= 50% 이면 icon_teleport 더블클릭 -> F9 키 두 번 입력 (위기 대응: 일단
     자리를 피하고 힐). 힐은 원래 icon_heel 더블클릭이었는데, 사용자 요청으로 F9
     키보드 단축키 두 번으로 변경했다 (press_heel_key()) -- 아이콘 탐지/F2 탭
     전환이 필요 없어서 더 빠르다.
   - MP <= 5%가 2틱 연속으로 나오면 루프 종료 -- 더 이상 사냥을 지속할 마력이
     없다고 보고 ensure_step2()로 넘어간다: hotel_key 확인(없으면 [1단계]부터)
     -> [2단계](여관 이동 -> 메디테이션) -> HP 100% / MP 준비값 대기, 까지 전부 자동으로
     처리하고 다음 사이클([3단계]) 진입 준비가 된 상태로 반환한다 (같은
     SerialLink 연결을 그대로 재사용 -- 재접속 안 함). 1틱만 보고 바로
     반응하지 않는 이유는 실기에서 확인됨: OCR이 자릿수를 통째로 잘못 읽어
     (예: "358"을 "3"으로) MP가 실제로는 70% 넘게 남아있는데도 5% 이하로
     오인식해서 여관키를 쓴 적이 있었다.
   - (위 두 경우가 아니면) MP가 5틱 연속으로 줄지 않았으면 icon_teleport 더블클릭
     -- 자동사냥(ATS)이 스킬을 쓰면 MP가 소모되는데, 그게 계속 안 줄었다는 건 근처에
     잡을 몬스터가 없어서 ATS가 멈춰 있다는 뜻으로 보고, 사냥터를 옮기기 위해 다시
     텔레포트한다. 1틱만 보고 바로 반응하면 OCR/타이밍 노이즈(스킬이 마침 그 틱에
     0 코스트였다든가)에도 반응해버려서 5틱 연속 조건으로 완화했다.
   - icon_ats_off가 감지되면 ATS가 자동으로 꺼진 것으로 보고 즉시 모니터링을
     종료한 뒤 ensure_step2()를 통해 [2단계]부터 다시 진행한다.

MP 5% 이하 복귀 조건을 HP 비상 텔레포트보다 먼저 평가한다. 두 값이
동시에 임계값 이하면 사망 위험을 줄이기 위해 MP 2틱 확인을 생략하고 즉시
[2단계]로 복귀한다. HP가 안전하면 기존처럼 MP 2틱 연속 확인으로 OCR
오판을 방지한다.

icon_ats_off/icon_teleport 둘 다 hotel_key/meditation과 같은 F2
quick-slot 탭에 있으므로 step_move_to_hotel의
ensure_skill_tab()/double_click_region()을 그대로 재사용한다. HP/MP 판독은
pc/detector/hpmp.py의 앵커+오프셋 방식 감지기를 그대로 쓴다 (이 프로젝트에서 가장
많이 검증된 부분).

All mouse movement/clicking goes through the Arduino (SerialLink), never
a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.detector.any_presence_detector import AnyPresenceDetector, build_icon_detector  # noqa: E402
from pc.detector.presence_detector import PresenceResult  # noqa: E402
from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.hpmp import build_hp_mp_detectors  # noqa: E402
from pc.detector.ocr_reader import GaugeTextReader  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.routine.step_move_to_hotel import ensure_skill_tab, double_click_region, _capture_and_convert  # noqa: E402

MONITOR_INTERVAL_S = 1.0
HP_HEAL_PERCENT = 70.0
HP_EMERGENCY_PERCENT = 50.0
MP_EXIT_PERCENT = 5.0
HP_HEAL_CONSECUTIVE_TICKS = 2

# A serial ACK only confirms that the Arduino emitted the HID event; it
# does not mean the game accepted it. Let the teleport transition finish
# before healing, hold F9 long enough to cross a game input poll, and do
# not restart another teleport every monitor tick while HP is still low.
EMERGENCY_TELEPORT_SETTLE_S = 1.5
EMERGENCY_ACTION_COOLDOWN_S = 3.0
HEEL_KEY_HOLD_MS = 100
HEEL_KEY_INTERVAL_S = 0.12

# Confirmed live: a single-tick OCR misread (e.g. "358" -> "3", a digit
# dropped rather than the "/"-misread ResilientGaugeReader already
# guards against) can look exactly like a real MP<=5% reading and
# trigger the [2단계] hand-off while MP was actually still >70%. Require
# the low reading to hold for this many *consecutive* ticks before
# trusting it -- one bad OCR tick surrounded by normal ones won't
# survive that, a genuine MP crash will.
MP_EXIT_CONSECUTIVE_TICKS = 2

# MP naturally holds steady/ticks sideways by a point or two between
# reads even while ATS is actively fighting (OCR/timing noise, a skill
# that happened to cost 0 this exact tick, etc.) -- reacting to a single
# non-decreasing tick was too trigger-happy. Only teleport once MP has
# failed to drop for this many *consecutive* ticks in a row.
MP_STAGNANT_TICKS_BEFORE_TELEPORT = 5

# Safety cap so a stuck read (e.g. HP/MP anchor never re-appears) can't
# spin this forever unattended -- normal exit is always the MP <= 5%
# condition well before this. ~2 hours at MONITOR_INTERVAL_S=1.0.
MAX_TICKS = 7200


def build_ats_off_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["ats_off"], project_root, panel=skill_panel)


def build_ats_on_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["ats_on"], project_root, panel=skill_panel)


def build_teleport_detector(settings: dict, project_root: Path, skill_panel: SkillPanelLocator) -> AnyPresenceDetector:
    return build_icon_detector(settings["icons"]["teleport"], project_root, panel=skill_panel)


def _click_icon(link: SerialLink, settings: dict, project_root: Path, skill_panel: SkillPanelLocator,
                 window_title: str, screen_capture_cls, detector: AnyPresenceDetector, label: str) -> bool:
    """Shared by toggle_ats_on()/click_teleport_icon(): press F2, locate
    one icon fresh, double-click it if present."""
    if not ensure_skill_tab(link):
        print(f"    [{label}] F2 keypress not ACKed")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    result: PresenceResult = detector.measure(frame)
    if not result.present or result.region is None:
        print(f"    [{label}] not present (score={result.match_score:.3f})")
        return False
    ok = double_click_region(link, converter, result.region)
    print(f"    [{label}] double-click -> {'ok' if ok else 'FAILED (missing ACK)'}")
    return ok


def toggle_ats_on(link: SerialLink, settings: dict, project_root: Path, skill_panel: SkillPanelLocator,
                   window_title: str, screen_capture_cls) -> bool:
    """Ensures ATS ends up ON. ats_off/ats_on are a mutually-exclusive
    toggle pair (see icons config) -- if ats_off is present, ATS is
    currently OFF, so double-click it. If it's not present, that's not
    automatically a failure: on every loop after the first in
    pc/routine/run_all.py, ATS is already ON from the previous cycle (
    nothing turns it off in between), so ats_off legitimately won't be
    there -- only fail if ats_on isn't showing either (icon layout/tab
    genuinely wrong)."""
    if not ensure_skill_tab(link):
        print("    [ats_off] F2 keypress not ACKed")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)

    ats_off = build_ats_off_detector(settings, project_root, skill_panel).measure(frame)
    if ats_off.present and ats_off.region is not None:
        ok = double_click_region(link, converter, ats_off.region)
        print(f"    [ats_off] double-click -> {'ok' if ok else 'FAILED (missing ACK)'}")
        return ok

    ats_on = build_ats_on_detector(settings, project_root, skill_panel).measure(frame)
    if ats_on.present:
        print("    [ats_off] not present, but ats_on already is -- ATS already ON, nothing to do")
        return True

    print(f"    [ats_off] neither ats_off nor ats_on present (ats_off score={ats_off.match_score:.3f})")
    return False


def click_teleport_icon(link: SerialLink, settings: dict, project_root: Path, skill_panel: SkillPanelLocator,
                         window_title: str, screen_capture_cls) -> bool:
    detector = build_teleport_detector(settings, project_root, skill_panel)
    return _click_icon(link, settings, project_root, skill_panel, window_title, screen_capture_cls, detector, "teleport")


def press_heel_key(link: SerialLink) -> bool:
    """[4단계]'s heal action -- press F9 twice, per the user's explicit
    change from double-clicking icon_heel to a keyboard shortcut. No
    icon detection/F2 tab involved, unlike the other actions here."""
    first = link.send_and_wait("KEY", f"F9 {HEEL_KEY_HOLD_MS}")
    if first is None or not first.ok:
        print("    [heel] F9 (1st) -> FAILED (missing ACK)")
        return False
    time.sleep(HEEL_KEY_INTERVAL_S)
    second = link.send_and_wait("KEY", f"F9 {HEEL_KEY_HOLD_MS}")
    ok = second is not None and second.ok
    print(
        f"    [heel] F9 x2 (hold={HEEL_KEY_HOLD_MS}ms, "
        f"gap={HEEL_KEY_INTERVAL_S:.2f}s) -> {'ok' if ok else 'FAILED (missing ACK)'}"
    )
    return ok


def monitor_and_hunt(link: SerialLink, settings: dict, project_root: Path, skill_panel: SkillPanelLocator,
                      hp_detector, mp_detector, window_title: str, screen_capture_cls) -> bool:
    """Runs the 1-second monitoring loop until MP <= MP_EXIT_PERCENT for
    MP_EXIT_CONSECUTIVE_TICKS ticks in a row (or MAX_TICKS is hit, as a
    safety fallback). Returns True if it's time to
    hand off to [2단계] (the normal MP <= 5% exit), False if it stopped
    for the MAX_TICKS safety fallback instead (caller should NOT hand
    off automatically in that case -- something's likely wrong, e.g. HP/
    MP stopped being readable)."""
    last_mp_current: Optional[int] = None
    stagnant_ticks = 0
    low_mp_ticks = 0
    low_heal_ticks = 0
    last_emergency_time: Optional[float] = None
    heal_baseline_hp: Optional[int] = None
    ats_off_detector = build_ats_off_detector(settings, project_root, skill_panel)

    for tick in range(1, MAX_TICKS + 1):
        time.sleep(MONITOR_INTERVAL_S)

        with screen_capture_cls(window_title=window_title) as cap:
            frame = cap.grab()

        hp_result = hp_detector.measure(frame)
        mp_result = mp_detector.measure(frame)
        if hp_result is None or mp_result is None:
            print(f"  tick {tick}: [warn] HP/MP read failed, skipping this tick")
            continue

        hp = hp_result.reading
        mp = mp_result.reading
        print(f"  tick {tick}: HP {hp.current}/{hp.maximum} ({hp.percent:.1f}%)  MP {mp.current}/{mp.maximum} ({mp.percent:.1f}%)")

        ats_off = ats_off_detector.measure(frame)
        if ats_off.present:
            print(
                f"    [ATS OFF] icon_ats_off detected (score={ats_off.match_score:.3f}) "
                "-- immediate handoff to [2단계]"
            )
            return True

        if heal_baseline_hp is not None:
            delta = hp.current - heal_baseline_hp
            print(f"    [heel verify] HP change after last heal: {delta:+d} ({heal_baseline_hp} -> {hp.current})")
            heal_baseline_hp = None

        # Returning to the hotel takes priority over emergency combat
        # actions. When both resources are critical, waiting for a
        # second MP OCR sample plus teleport/heal delays the hotel key
        # long enough to risk death. Keep the two-sample OCR guard only
        # while HP is above the emergency threshold.
        if mp.percent <= MP_EXIT_PERCENT:
            low_mp_ticks += 1
            if hp.percent <= HP_EMERGENCY_PERCENT:
                print(
                    f"    [critical exit] MP <= {MP_EXIT_PERCENT:.0f}% and "
                    f"HP <= {HP_EMERGENCY_PERCENT:.0f}% -- immediate handoff to [2단계]"
                )
                return True
            print(f"    MP <= 5% ({low_mp_ticks}/{MP_EXIT_CONSECUTIVE_TICKS} consecutive ticks)")
            if low_mp_ticks >= MP_EXIT_CONSECUTIVE_TICKS:
                print("    [exit] MP <= 5% held for 2 consecutive ticks -- ending [4단계], hand off to [2단계]")
                return True
        else:
            low_mp_ticks = 0

        handled_emergency = False
        if hp.percent <= HP_EMERGENCY_PERCENT:
            low_heal_ticks = 0
            handled_emergency = True
            stagnant_ticks = 0  # already teleported this tick for a different reason
            now = time.monotonic()
            cooldown_ready = (
                last_emergency_time is None
                or now - last_emergency_time >= EMERGENCY_ACTION_COOLDOWN_S
            )
            if cooldown_ready:
                print(f"    [emergency] HP <= {HP_EMERGENCY_PERCENT:.0f}% -- teleport, settle, then heal")
                teleported = click_teleport_icon(
                    link, settings, project_root, skill_panel, window_title, screen_capture_cls
                )
                if teleported:
                    print(f"    [emergency] waiting {EMERGENCY_TELEPORT_SETTLE_S:.1f}s for teleport transition...")
                    time.sleep(EMERGENCY_TELEPORT_SETTLE_S)
                else:
                    print("    [emergency] teleport failed; attempting heal in place")
                healed = press_heel_key(link)
                if healed:
                    heal_baseline_hp = hp.current
                last_emergency_time = time.monotonic()
            else:
                remaining = EMERGENCY_ACTION_COOLDOWN_S - (now - last_emergency_time)
                print(f"    [emergency] action cooldown ({max(0.0, remaining):.1f}s remaining)")

        elif hp.percent <= HP_HEAL_PERCENT:
            handled_emergency = True
            low_heal_ticks += 1
            if low_heal_ticks >= HP_HEAL_CONSECUTIVE_TICKS:
                print(
                    f"    [heal] HP <= {HP_HEAL_PERCENT:.0f}% "
                    f"({low_heal_ticks} consecutive ticks) -- pressing F9 twice"
                )
                healed = press_heel_key(link)
                if healed:
                    heal_baseline_hp = hp.current
            else:
                print(
                    f"    [heal] HP <= {HP_HEAL_PERCENT:.0f}% "
                    f"({low_heal_ticks}/{HP_HEAL_CONSECUTIVE_TICKS} consecutive ticks)"
                )
        else:
            low_heal_ticks = 0

        if not handled_emergency:
            if last_mp_current is not None and mp.current >= last_mp_current:
                stagnant_ticks += 1
            else:
                stagnant_ticks = 0

            if stagnant_ticks >= MP_STAGNANT_TICKS_BEFORE_TELEPORT:
                print(f"    MP hasn't decreased for {stagnant_ticks} consecutive ticks -- teleporting to find monsters")
                click_teleport_icon(link, settings, project_root, skill_panel, window_title, screen_capture_cls)
                stagnant_ticks = 0

        last_mp_current = mp.current

    print(f"  [warn] hit MAX_TICKS ({MAX_TICKS}) without MP dropping to {MP_EXIT_PERCENT}% -- stopping as a safety fallback.")
    return False


def _wait_for_ready_hp_mp(hp_detector, mp_detector, window_title: str, screen_capture_cls,
                          mp_ready_percent: float,
                          poll_interval_s: float = MONITOR_INTERVAL_S) -> None:
    """Poll until HP is full and MP reaches the configured readiness level --
    meditation (from [2단계]) doesn't complete instantly, and the user's
    design has [3단계] only start once both gauges are ready. A None
    reading (anchor briefly not found, etc.) just
    waits and retries rather than erroring -- this isn't safety-critical
    like the HP/MP watchdog elsewhere, it's a readiness gate."""
    print(f"  HP 100% / MP {mp_ready_percent:.0f}% 이상 대기 중...")
    while True:
        with screen_capture_cls(window_title=window_title) as cap:
            frame = cap.grab()
        hp_result = hp_detector.measure(frame)
        mp_result = mp_detector.measure(frame)
        if hp_result is not None and mp_result is not None:
            hp = hp_result.reading
            mp = mp_result.reading
            if hp.current >= hp.maximum and mp.percent >= mp_ready_percent:
                print(f"  HP {hp.current}/{hp.maximum} (100%)  MP {mp.current}/{mp.maximum} ({mp.percent:.1f}%) -- 대기 종료")
                return
            print(f"    HP {hp.current}/{hp.maximum} ({hp.percent:.1f}%)  MP {mp.current}/{mp.maximum} ({mp.percent:.1f}%) -- 대기...")
        time.sleep(poll_interval_s)


def ensure_step2(settings: dict, project_root: Path, window_title: str, link: SerialLink, skill_panel: SkillPanelLocator,
                  hp_detector, mp_detector, hotel_text, rent_room_text, ok_button_text,
                  screen_capture_cls, force_run: bool = False) -> bool:
    """Runs [2단계], first running [1단계] if icon_hotel_key isn't
    present in roi_skill (the 4-hour room rental can expire mid-loop, so
    this precondition is re-checked every time, not just once at
    startup) -- then waits for HP 100% and the configured MP readiness
    percentage before returning. The recovery action always runs on
    entry; already-full HP/MP no longer skips the meditation cast.
    Shared by run()'s MP<=5% handoff below and
    pc/routine/run_all.py's initial entry point, so both go through
    the exact same "ensure the precondition, run [2단계], wait for full
    MP" sequence the user specified."""
    import pc.routine.step_buy_hotel_key as step1
    import pc.routine.step_move_to_hotel as step2
    mp_ready_percent = float(settings.get("step2", {}).get("mp_ready_percent", 97.0))

    # The hotel key is a persistent precondition for every [2단계]
    # entry, independent of current MP.
    with screen_capture_cls(window_title=window_title) as cap:
        frame = cap.grab()
    hotel_key = build_icon_detector(
        settings["icons"]["hotel_key"], project_root, panel=skill_panel
    ).measure(frame)
    if not hotel_key.present:
        print("  hotel_key not present -- running [1단계] first...")
        ok = step1.run(
            settings, project_root, window_title, link, skill_panel,
            hotel_text, rent_room_text, ok_button_text, screen_capture_cls,
        )
        if not ok:
            print("  [1단계] failed.")
            return False

    ok = step2.run(settings, project_root, window_title, link, skill_panel, mp_detector, screen_capture_cls)
    if not ok:
        print("  [2단계] failed.")
        return False
    _wait_for_ready_hp_mp(
        hp_detector, mp_detector, window_title, screen_capture_cls, mp_ready_percent
    )
    return True


def run(settings: dict, project_root: Path, window_title: str, link: SerialLink, skill_panel: SkillPanelLocator,
        hp_detector, mp_detector, hotel_text, rent_room_text, ok_button_text, screen_capture_cls) -> bool:
    """Full [4단계]: ATS toggle + 1s monitoring loop + auto-handoff to
    [2단계] (via ensure_step2(), including its own [1단계]-if-needed
    precondition and MP-100% wait) once MP <= 5%, as a reusable function
    (for pc/routine/run_all.py) instead of a script entry point. Returns
    True only if it got all the way through the hand-off and
    ensure_step2() also succeeded -- False if the ATS toggle failed,
    the monitoring loop ended via the MAX_TICKS
    safety fallback instead of the normal MP<=5% exit, or the hand-off
    itself failed."""
    print("[1/2] toggling ATS ON (double-clicking icon_ats_off)...")
    ok = toggle_ats_on(link, settings, project_root, skill_panel, window_title, screen_capture_cls)
    if not ok:
        print("[stop] could not toggle ATS on (neither ats_off nor ats_on present, or click failed).")
        return False

    print("[2/2] monitoring HP/MP every 1s until MP <= 5%...")
    should_hand_off = monitor_and_hunt(link, settings, project_root, skill_panel, hp_detector, mp_detector, window_title, screen_capture_cls)

    if not should_hand_off:
        print("[stop] not handing off to [2단계] -- monitoring loop ended abnormally (see [warn] above).")
        return False

    print("Handing off to [2단계] (hotel_key 확인 -> 여관 이동 + 메디테이션 -> HP/MP 준비 대기)...")
    ok = ensure_step2(settings, project_root, window_title, link, skill_panel, hp_detector, mp_detector,
                       hotel_text, rent_room_text, ok_button_text, screen_capture_cls)
    print(f"[2단계] handoff -> {'ok' if ok else 'FAILED'}")
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

    print("Loading OCR models (HP/MP gauge + Korean dialog)...")
    gauge_reader = GaugeTextReader()
    hp_detector, mp_detector = build_hp_mp_detectors(settings, _PROJECT_ROOT, gauge_reader)

    # Only needed for ensure_step2()'s [1단계]-if-needed fallback, but
    # built unconditionally -- cheap (no OCR runs until actually used)
    # and keeps this script's standalone `python -m
    # pc.routine.step_auto_hunt` usable on its own, same as before.
    from pc.detector.chat_reader import KoreanTextReader
    import pc.routine.step_buy_hotel_key as step1
    korean_reader = KoreanTextReader()
    hotel_text = step1.build_hotel_text_locator(settings, _PROJECT_ROOT, korean_reader)
    rent_room_text = step1.build_rent_room_text_locator(settings, _PROJECT_ROOT, korean_reader)
    ok_button_text = step1.build_ok_button_text_locator(settings, _PROJECT_ROOT, korean_reader)

    serial_cfg = settings["serial"]
    try:
        with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
            time.sleep(2.5)  # Leonardo boot delay after port open
            link.send("PING")
            time.sleep(0.3)
            link.poll_acks()

            ok = run(settings, _PROJECT_ROOT, window_title, link, skill_panel, hp_detector, mp_detector,
                     hotel_text, rent_room_text, ok_button_text, ScreenCapture)
            if not ok:
                sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[stopped] Ctrl+C")


if __name__ == "__main__":
    main()
