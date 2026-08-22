"""전체 통합 루프 (사용자가 재정의한 버전).

[2단계] 진입 시도 (icon_hotel_key 없으면 [1단계]부터, 끝나면 자동 [2단계])
-> MP 100% 대기 -> 무한 반복: [3단계] -> [4단계] (MP<=5% 시 내부적으로 다시
"[2단계] 진입 시도(hotel_key 확인 포함) -> MP 100% 대기"까지 자동 실행) -> 다시
[3단계] -> ...

"hotel_key 확인 -> [1단계](필요시) -> [2단계] -> MP 100% 대기"는 최초 진입 시점과
[4단계]의 MP<=5% 핸드오프 시점 둘 다에서 완전히 동일한 절차이므로, 이 로직은
step_auto_hunt.ensure_step2() 하나에만 있고 여기서는 그걸 그대로 재사용한다
(중복 구현 금지 -- 두 곳이 조금이라도 달라지면 사이클마다 다르게 동작하는 버그가
됨). 그래서 이 파일의 while 루프는 [3단계] -> [4단계] 두 줄이 사실상 전부다;
[4단계] 자신이 다음 사이클 진입("[2단계]+MP 100%")까지 끝내놓고 반환한다.

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

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.detector.skill_panel import SkillPanelLocator  # noqa: E402
from pc.detector.chat_reader import KoreanTextReader  # noqa: E402
from pc.detector.ocr_reader import GaugeTextReader  # noqa: E402
from pc.detector.hpmp import build_hp_mp_detectors  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402

import pc.routine.step_buy_hotel_key as step1  # noqa: E402
import pc.routine.step_move_to_wasteland as step3  # noqa: E402
import pc.routine.step_auto_hunt as step4  # noqa: E402


def main() -> None:
    from pc.config.config_loader import load_settings
    from pc.capture.screen_capture import ScreenCapture
    from pc.capture.window_locator import WindowNotFoundError
    from pc.serial.port_finder import resolve_port

    settings = load_settings()
    window_title = settings["capture"]["window_title"]
    project_root = _PROJECT_ROOT

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
            time.sleep(2.5)  # Leonardo boot delay after port open
            link.send("PING")
            time.sleep(0.3)
            link.poll_acks()

            print("=== 초기 진입: [2단계] (hotel_key 확인 -> 필요시 [1단계] -> [2단계] -> MP 100% 대기) ===")
            ok = step4.ensure_step2(settings, project_root, window_title, link, skill_panel, hp_detector, mp_detector,
                                     hotel_text, rent_room_text, ok_button_text, ScreenCapture)
            if not ok:
                print("[stop] 초기 진입 실패.")
                sys.exit(1)

            cycle = 0
            while True:
                cycle += 1
                print(f"\n===== 사이클 {cycle}: [3단계] 버려진땅 이동 =====")
                step3_result = step3.run(
                    settings, project_root, window_title, link, skill_panel,
                    wasteland_text, gate_dest_text, step_forward_text, korean_reader,
                    ScreenCapture, hp_detector=hp_detector,
                )
                if step3_result is None:
                    print("[3단계] recovery requested -> running [2단계]")
                    ok = step4.ensure_step2(
                        settings, project_root, window_title, link, skill_panel,
                        hp_detector, mp_detector, hotel_text, rent_room_text,
                        ok_button_text, ScreenCapture,
                    )
                    if not ok:
                        print(f"[stop] cycle {cycle}: emergency [2단계] failed.")
                        sys.exit(1)
                    cycle -= 1
                    continue
                if not step3_result:
                    print(f"[stop] 사이클 {cycle}: [3단계] 실패.")
                    sys.exit(1)

                print(f"===== 사이클 {cycle}: [4단계] ATS + 사냥 (MP<=5% 시 내부적으로 다음 사이클 진입까지 처리) =====")
                ok = step4.run(settings, project_root, window_title, link, skill_panel, hp_detector, mp_detector,
                                hotel_text, rent_room_text, ok_button_text, ScreenCapture)
                if not ok:
                    print(f"[stop] 사이클 {cycle}: [4단계] (또는 그 안의 다음 사이클 진입) 실패.")
                    sys.exit(1)
    except WindowNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[stopped] Ctrl+C")
if __name__ == "__main__":
    main()
