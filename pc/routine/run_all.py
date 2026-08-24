"""전체 통합 루프 (사용자가 재정의한 버전).

[2단계] 진입 시도 (icon_hotel_key 없으면 [1단계]부터, 끝나면 자동 [2단계])
-> HP 100% / MP 97% 이상 대기 -> 무한 반복: [3단계] -> [4단계] (MP<=5% 시 내부적으로 다시
"[2단계] 진입 시도(hotel_key 확인 포함) -> HP/MP 준비 대기"까지 자동 실행) -> 다시
[3단계] -> ...

"hotel_key 확인 -> [1단계](필요시) -> [2단계] -> HP/MP 준비 대기"는 최초 진입 시점과
[4단계]의 MP<=5% 핸드오프 시점 둘 다에서 완전히 동일한 절차이므로, 이 로직은
step_auto_hunt.ensure_step2() 하나에만 있고 여기서는 그걸 그대로 재사용한다
(중복 구현 금지 -- 두 곳이 조금이라도 달라지면 사이클마다 다르게 동작하는 버그가
됨). 그래서 이 파일의 while 루프는 [3단계] -> [4단계] 두 줄이 사실상 전부다;
[4단계] 자신이 다음 사이클 진입("[2단계]+HP/MP 준비")까지 끝내놓고 반환한다.

어느 스텝이든 실패(False 반환)하면 전체 루프를 멈춘다 -- 실패 상태에서 억지로
계속하면 엉뚱한 동작을 반복할 위험이 있어서, 사람이 확인할 수 있게 멈추는 쪽을
택했다.

OCR 모델(Korean dialog용 / HP,MP gauge용)과 각 스텝의 RememberedDialogText
캐시들, SkillPanelLocator는 전부 여기서 딱 한 번만 만들어서 루프 내내
재사용한다 -- 개별 스텝 스크립트를 매번 새 프로세스로 실행할 때와 달리, 이 통합
루프 안에서는 텍스트 타겟마다 OCR이 프로세스 생애 전체에서 정말 한 번만 돈다
(pc/detector/remembered_text.py 참고).

All mouse movement/clicking goes through the Arduino (SerialLink), never
a Python input-simulation call -- see CLAUDE.md.
"""
from __future__ import annotations

import _thread
import os
import sys
import random
import threading
import traceback
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import TextIO

import cv2

_PROJECT_ROOT = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])
)
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.chat_reader import KoreanTextReader  # noqa: E402
from pc.detector.ocr_reader import GaugeTextReader  # noqa: E402
from pc.detector.hpmp import build_hp_mp_detectors  # noqa: E402
from pc.detector.template_locator import locate_template  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.routine.timing import sleep_jittered  # noqa: E402
from pc.routine.death_recovery import (  # noqa: E402
    DeathAwareScreenCapture,
    DeathRecoveryController,
    DeathRecoveryRequested,
)
from pc.routine.step_move_to_hotel import (  # noqa: E402
    _capture_and_convert,
    set_cursor_park_region,
)

import pc.routine.step_buy_hotel_key as step1  # noqa: E402
import pc.routine.step_move_to_wasteland as step3  # noqa: E402
import pc.routine.step_auto_hunt as step4  # noqa: E402


DEFAULT_RESTART_DELAY_S = 5.0
DEFAULT_MIN_DUNGEON_MINUTES_FOR_STEP3 = 9
DEFAULT_PRE_STEP4_TELEPORT_SETTLE_S = 1.5
RESUME_WINDOW_START_HOUR = 7
RESUME_WINDOW_START_MINUTE = 30
RESUME_WINDOW_END_HOUR = 8
RESUME_WINDOW_END_MINUTE = 30
WAIT_POLL_SECONDS = 30.0

_routine_log_file: TextIO | None = None


class _TeeStream:
    """Write every print to both the original stream and a UTF-8 log."""

    def __init__(self, screen: TextIO, log_file: TextIO):
        self._screen = screen
        self._log_file = log_file
        self._lock = threading.RLock()

    def write(self, text: str) -> int:
        with self._lock:
            self._screen.write(text)
            self._log_file.write(text)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            self._screen.flush()
            self._log_file.flush()

    def isatty(self) -> bool:
        return self._screen.isatty()

    @property
    def encoding(self):
        return getattr(self._screen, "encoding", "utf-8")


def _enable_file_logging() -> Path:
    """Tee stdout/stderr to one timestamped file for this process."""
    global _routine_log_file
    log_dir = _PROJECT_ROOT / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"routine_{timestamp}.log"
    _routine_log_file = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _TeeStream(sys.stdout, _routine_log_file)
    sys.stderr = _TeeStream(sys.stderr, _routine_log_file)
    print(f"[log] file: {log_path}")
    return log_path


def _choose_resume_time(now: datetime) -> datetime:
    """Choose one future time in the next available 07:30-08:30 window."""
    start = now.replace(
        hour=RESUME_WINDOW_START_HOUR,
        minute=RESUME_WINDOW_START_MINUTE,
        second=0,
        microsecond=0,
    )
    end = now.replace(
        hour=RESUME_WINDOW_END_HOUR,
        minute=RESUME_WINDOW_END_MINUTE,
        second=0,
        microsecond=0,
    )
    if now >= end:
        start += timedelta(days=1)
        end += timedelta(days=1)
    elif now > start:
        start = now
    span_seconds = max(0.0, (end - start).total_seconds())
    return start + timedelta(seconds=random.uniform(0.0, span_seconds))


def _wait_until_resume(target: datetime) -> None:
    """Wait without HID input; Ctrl+C remains able to stop the process."""
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        sleep_jittered(min(WAIT_POLL_SECONDS, remaining))


def _click_startup_chat(link: SerialLink, settings: dict, project_root: Path,
                        window_title: str, screen_capture_cls) -> bool:
    """Single-click a random point in the centered 30% of roi_chatting."""
    chat_cfg = settings["chat"]
    template = cv2.imread(str(project_root / chat_cfg["template"]))
    if template is None:
        print("[startup] roi_chatting template could not be loaded")
        return False
    frame, converter = _capture_and_convert(window_title, screen_capture_cls)
    match = locate_template(
        frame, template, float(chat_cfg.get("match_threshold", 0.5))
    )
    if match is None:
        print("[startup] roi_chatting not found")
        return False
    print(f"[startup] roi_chatting found: {match.region}")
    set_cursor_park_region(match.region)
    return step3.click_region_once(link, converter, match.region)


def _run_once() -> float:
    """Run one session; ordinary failures return to the supervisor."""
    from pc.config.config_loader import load_settings
    from pc.capture.screen_capture import ScreenCapture
    from pc.capture.window_locator import WindowNotFoundError
    from pc.serial.port_finder import resolve_port

    settings = load_settings()
    window_title = settings["capture"]["window_title"]
    project_root = _PROJECT_ROOT
    restart_delay_s = float(
        settings.get("routine", {}).get("restart_delay_seconds", DEFAULT_RESTART_DELAY_S)
    )
    routine_cfg = settings.get("routine", {})
    pause_on_low_dungeon_time = bool(
        routine_cfg.get("pause_on_low_dungeon_time", True)
    )
    pause_override = os.environ.get("ROUTINE_PAUSE_ON_LOW_DUNGEON_TIME")
    if pause_override is not None:
        pause_on_low_dungeon_time = pause_override.strip().lower() in {
            "1", "true", "yes", "on",
        }
    minimum_dungeon_minutes = int(
        routine_cfg.get(
            "minimum_dungeon_minutes_for_step3",
            DEFAULT_MIN_DUNGEON_MINUTES_FOR_STEP3,
        )
    )
    minimum_minutes_override = os.environ.get("ROUTINE_MIN_DUNGEON_MINUTES")
    if minimum_minutes_override is not None:
        minimum_dungeon_minutes = max(0, int(minimum_minutes_override))
    pause_on_six_oclock_chat = bool(
        routine_cfg.get("pause_on_six_oclock_chat", True)
    )
    six_oclock_override = os.environ.get("ROUTINE_PAUSE_ON_SIX_OCLOCK_CHAT")
    if six_oclock_override is not None:
        pause_on_six_oclock_chat = six_oclock_override.strip().lower() in {
            "1", "true", "yes", "on",
        }
    teleport_before_step4 = bool(routine_cfg.get("teleport_before_step4", True))
    teleport_override = os.environ.get("ROUTINE_TELEPORT_BEFORE_STEP4")
    if teleport_override is not None:
        teleport_before_step4 = teleport_override.strip().lower() in {
            "1", "true", "yes", "on",
        }
    mp_stagnation_override = os.environ.get("ROUTINE_TELEPORT_ON_MP_STAGNATION")
    if mp_stagnation_override is not None:
        routine_cfg["teleport_on_mp_stagnation"] = (
            mp_stagnation_override.strip().lower() in {
                "1", "true", "yes", "on",
            }
        )
    pre_step4_teleport_settle_s = float(
        routine_cfg.get(
            "pre_step4_teleport_settle_seconds",
            DEFAULT_PRE_STEP4_TELEPORT_SETTLE_S,
        )
    )
    print(
        "[config] low dungeon-time pause: "
        f"{'enabled' if pause_on_low_dungeon_time else 'disabled'} "
        f"(at or below {minimum_dungeon_minutes} minutes)"
    )
    print(
        "[config] teleport before Step 4: "
        f"{'enabled' if teleport_before_step4 else 'disabled'}"
    )
    print(
        "[config] pause on '오전 6시' chat after Step 3: "
        f"{'enabled' if pause_on_six_oclock_chat else 'disabled'}"
    )
    print(
        "[config] teleport on MP stagnation: "
        f"{'enabled' if routine_cfg.get('teleport_on_mp_stagnation', True) else 'disabled'}"
    )

    roi_skill_cfg = settings["roi_skill"]
    skill_panel = SkillPanelLocator(
        project_root / roi_skill_cfg["template"], roi_skill_cfg["match_threshold"],
        roi_skill_cfg.get("search_region"),
    )

    print("Loading OCR models (Korean dialog + HP/MP gauge)...")
    korean_reader = KoreanTextReader()
    gauge_reader = GaugeTextReader()
    hp_detector, mp_detector = build_hp_mp_detectors(settings, project_root, gauge_reader)

    # [1단계]'s text locators -- only actually OCR'd if/when hotel_key
    # turns out to be missing (ensure_step2() checks first), but built
    # unconditionally so the cache is ready either way.
    hotel_text = step1.build_hotel_text_locator(settings, project_root, korean_reader)
    rent_room_text = step1.build_rent_room_text_locator(settings, project_root, korean_reader)
    ok_button_text = step1.build_ok_button_text_locator(settings, project_root, korean_reader)

    # [3단계]'s text locators
    wasteland_text = step3.build_wasteland_text_locator(settings, project_root, korean_reader)
    gate_dest_text = step3.build_gate_destination_text_locator(settings, project_root, korean_reader)
    step_forward_text = step3.build_step_forward_text_locator(settings, project_root, korean_reader)

    serial_cfg = settings["serial"]
    try:
        with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
            sleep_jittered(2.5)  # Leonardo boot delay after port open
            link.send("PING")
            sleep_jittered(0.3)
            link.poll_acks()

            death_controller = DeathRecoveryController(
                settings, project_root, window_title, link
            )
            routine_capture_cls = partial(
                DeathAwareScreenCapture, ScreenCapture, death_controller
            )

            print("[startup] clicking roi_chatting once before F2...")
            if not _click_startup_chat(
                link, settings, project_root, window_title, routine_capture_cls
            ):
                print("[startup] roi_chatting click failed -- restarting session")
                return restart_delay_s

            print("[startup] pressing F2 once before entering the routine...")
            if not link.send_and_wait("KEY", "F2"):
                print("[startup] F2 keypress not ACKed -- restarting session")
                return restart_delay_s

            print("=== 초기 진입: [2단계] (hotel_key 확인 -> 필요시 [1단계] -> [2단계] -> HP 100% / MP 97% 이상 대기) ===")
            ok = step4.ensure_step2(settings, project_root, window_title, link, skill_panel, hp_detector, mp_detector,
                                     hotel_text, rent_room_text, ok_button_text, routine_capture_cls)
            if not ok:
                print("[stop] 초기 진입 실패.")
                return restart_delay_s

            cycle = 0
            skip_dungeon_check_once = False
            while True:
                cycle += 1
                if skip_dungeon_check_once:
                    skip_dungeon_check_once = False
                    dungeon_minutes = None
                    print("[pre-step3] post-reset cycle -- skipping stale chat check once")
                else:
                    print("[pre-step3] reading dungeon time from chat...")
                    dungeon_minutes = step4.read_and_log_chat(
                        settings, project_root, window_title, routine_capture_cls,
                        korean_reader,
                        save_if_at_or_below=minimum_dungeon_minutes,
                    )
                if (
                    pause_on_low_dungeon_time
                    and dungeon_minutes is not None
                    and dungeon_minutes <= minimum_dungeon_minutes
                ):
                    resume_at = _choose_resume_time(datetime.now())
                    print(
                        f"[wait] dungeon_minutes={dungeon_minutes} is at or below "
                        f"{minimum_dungeon_minutes}; Step 3 is paused."
                    )
                    print(
                        f"[wait] no input until randomized resume time: "
                        f"{resume_at:%Y-%m-%d %H:%M:%S}"
                    )
                    _wait_until_resume(resume_at)
                    print("[resume] randomized time reached -- restarting from Step 2")
                    ok = step4.ensure_step2(
                        settings, project_root, window_title, link, skill_panel,
                        hp_detector, mp_detector, hotel_text, rent_room_text,
                        ok_button_text, routine_capture_cls, force_run=True,
                    )
                    if not ok:
                        print("[resume] Step 2 failed; returning to normal recovery")
                        return restart_delay_s
                    skip_dungeon_check_once = True
                    cycle -= 1
                    continue
                print(f"\n===== 사이클 {cycle}: [3단계] 버려진땅 이동 =====")
                step3_result = step3.run(
                    settings, project_root, window_title, link, skill_panel,
                    wasteland_text, gate_dest_text, step_forward_text, korean_reader,
                    routine_capture_cls, hp_detector=hp_detector,
                    after_forward_click=(
                        lambda: step4.chat_contains_text(
                            settings, project_root, window_title,
                            routine_capture_cls, korean_reader, "오전 6시",
                        )
                    ) if pause_on_six_oclock_chat else None,
                )
                if step3_result is step3.Step3Result.WAIT_FOR_DUNGEON_RESET:
                    resume_at = _choose_resume_time(datetime.now())
                    print(
                        "[wait] '오전 6시' was found immediately after "
                        "clicking '발을 내딛는다.'; entering wait mode."
                    )
                    print(
                        f"[wait] no input until randomized resume time: "
                        f"{resume_at:%Y-%m-%d %H:%M:%S}"
                    )
                    _wait_until_resume(resume_at)
                    print(
                        "[resume] randomized time reached -- "
                        "restarting from Step 2"
                    )
                    ok = step4.ensure_step2(
                        settings, project_root, window_title, link,
                        skill_panel, hp_detector, mp_detector,
                        hotel_text, rent_room_text, ok_button_text,
                        routine_capture_cls, force_run=True,
                    )
                    if not ok:
                        print(
                            "[resume] Step 2 failed; returning to "
                            "normal recovery"
                        )
                        return restart_delay_s
                    skip_dungeon_check_once = True
                    cycle -= 1
                    continue
                if step3_result is None:
                    print("[3단계] recovery requested -> running [2단계]")
                    ok = step4.ensure_step2(
                        settings, project_root, window_title, link, skill_panel,
                        hp_detector, mp_detector, hotel_text, rent_room_text,
                        ok_button_text, routine_capture_cls, force_run=True,
                    )
                    if not ok:
                        print(f"[stop] cycle {cycle}: emergency [2단계] failed.")
                        return restart_delay_s
                    cycle -= 1
                    continue
                if not step3_result:
                    print(f"[stop] 사이클 {cycle}: [3단계] 실패.")
                    return restart_delay_s

                if teleport_before_step4:
                    print("[pre-step4] teleporting before ATS starts...")
                    if not step4.click_teleport_icon(
                        link, settings, project_root, skill_panel,
                        window_title, routine_capture_cls,
                    ):
                        print("[pre-step4] teleport failed -- restarting from Step 2")
                        return restart_delay_s
                    print(
                        f"[pre-step4] waiting {pre_step4_teleport_settle_s:.1f}s "
                        "for the teleport transition..."
                    )
                    sleep_jittered(max(0.0, pre_step4_teleport_settle_s))

                print(f"===== 사이클 {cycle}: [4단계] ATS + 사냥 (MP<=5% 시 내부적으로 다음 사이클 진입까지 처리) =====")
                ok = step4.run(settings, project_root, window_title, link, skill_panel, hp_detector, mp_detector,
                                hotel_text, rent_room_text, ok_button_text,
                                routine_capture_cls, korean_reader)
                if not ok:
                    print(f"[stop] 사이클 {cycle}: [4단계] (또는 그 안의 다음 사이클 진입) 실패.")
                    return restart_delay_s
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        return restart_delay_s


def main() -> None:
    """Restart failed sessions until the user explicitly presses Ctrl+C."""
    _enable_file_logging()
    if os.environ.get("ROUTINE_CONTROL_STDIN") == "1":
        def listen_for_gui_stop() -> None:
            for line in sys.stdin:
                if line.strip().upper() == "STOP":
                    _thread.interrupt_main()
                    return

        threading.Thread(target=listen_for_gui_stop, daemon=True).start()
    try:
        while True:
            restart_delay_s = DEFAULT_RESTART_DELAY_S
            try:
                restart_delay_s = _run_once()
            except DeathRecoveryRequested as error:
                restart_delay_s = 1.0
                print(f"[death] recovery requested: {error}; restarting from Step 2")
            except Exception as e:
                print(f"[recovery] unexpected {type(e).__name__}: {e}")
                traceback.print_exc()
            print(
                f"[recovery] restarting from the Step 2 entry precondition "
                f"in {restart_delay_s:.1f}s..."
            )
            sleep_jittered(max(0.1, restart_delay_s))
    except KeyboardInterrupt:
        print("\n[stopped] user requested Ctrl+C")
if __name__ == "__main__":
    main()
