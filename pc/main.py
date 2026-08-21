"""Full integration (development Step 10):

    Game Screen -> Capture -> HP/MP Detector -> Condition Manager
        -> Action Queue / Sequence Runner -> Serial -> Arduino -> HID

Usage (run from the project root, with the venv active):

    python -m pc.main

Runs until Ctrl+C. On stop -- or if the serial connection drops, or on
any unexpected crash -- always clears the action queue and sends STOP
to the Arduino so no key or mouse button is left held down (spec
section 11). The Arduino also self-releases everything if it goes
WATCHDOG_TIMEOUT_MS without hearing from the PC at all (see main.ino),
so a dead link is safe even if this process never gets to run its own
cleanup.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import serial as pyserial

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.capture.screen_capture import Region, ScreenCapture  # noqa: E402
from pc.capture.window_locator import WindowNotFoundError  # noqa: E402
from pc.detector.hpmp import build_hp_mp_detectors  # noqa: E402
from pc.detector.ocr_reader import GaugeTextReader  # noqa: E402
from pc.condition.condition import Condition  # noqa: E402
from pc.condition.condition_manager import ConditionManager, TriggeredAction  # noqa: E402
from pc.queue.action_queue import ActionQueue, QueuedAction  # noqa: E402
from pc.queue.dispatcher import ActionDispatcher  # noqa: E402
from pc.action.action_sequence import SequenceRunner  # noqa: E402
from pc.action.sequence_config import load_all_sequences  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.serial.port_finder import resolve_port  # noqa: E402

HEARTBEAT_INTERVAL_S = 1.0  # keeps the Arduino's watchdog satisfied during idle periods


def _build_capture(settings: Dict[str, Any]) -> ScreenCapture:
    cap_cfg = settings["capture"]
    if cap_cfg.get("window_title"):
        return ScreenCapture(window_title=cap_cfg["window_title"])
    region = Region(**cap_cfg["region"]) if cap_cfg.get("region") else None
    return ScreenCapture(monitor=cap_cfg.get("monitor", 1), region=region)


def _build_condition_manager(settings: Dict[str, Any]) -> ConditionManager:
    cond_cfg = settings["conditions"]
    conditions = [
        Condition(
            name=name,
            threshold_percent=cfg["threshold_percent"],
            cooldown_seconds=cfg["cooldown_seconds"],
        )
        for name, cfg in cond_cfg.items()
    ]
    keys = {name: cfg["key"] for name, cfg in cond_cfg.items()}
    return ConditionManager(conditions, keys)


class MacroApp:
    def __init__(self, settings: Dict[str, Any]):
        self.settings = settings
        self.cond_cfg = settings["conditions"]

        ocr_reader = GaugeTextReader()  # shared -- loading the model twice would be wasteful
        self.hp_detector, self.mp_detector = build_hp_mp_detectors(settings, _PROJECT_ROOT, ocr_reader)

        self.condition_manager = _build_condition_manager(settings)
        self.sequences = load_all_sequences(settings)

        serial_cfg = settings["serial"]
        port = resolve_port(serial_cfg["port"])
        print(f"Connecting to Arduino on {port}...", flush=True)
        self.link = SerialLink(port, serial_cfg["baud_rate"])
        self.action_queue = ActionQueue()
        self.dispatcher = ActionDispatcher(self.action_queue, self.link)
        self.runner = SequenceRunner(self._enqueue)

        self.capture = _build_capture(settings)

        self._last_heartbeat = 0.0

    def _enqueue(self, command_type: str, args: str) -> None:
        self.action_queue.push(QueuedAction(source="sequence", command_type=command_type, args=args))

    def _handle_triggers(self, fired: list) -> None:
        for action in fired:
            cfg = self.cond_cfg[action.condition_name]
            sequence_name = cfg.get("sequence")
            if sequence_name:
                sequence = self.sequences.get(sequence_name)
                if sequence is None:
                    print(f"\n[warn] condition {action.condition_name!r} references unknown sequence {sequence_name!r}")
                    continue
                print(f"\n[TRIGGER] {action.condition_name} -> sequence {sequence_name}")
                self.runner.start(sequence)
            else:
                print(f"\n[TRIGGER] {action.condition_name} -> key {action.key}")
                self.action_queue.push(
                    QueuedAction(source=action.condition_name, command_type="KEY", args=action.key)
                )

    def tick(self) -> Dict[str, Optional[float]]:
        """One full cycle: capture -> detect -> condition -> dispatch. Never sleeps."""
        frame = self.capture.grab()
        hp_result = self.hp_detector.measure(frame)
        mp_result = self.mp_detector.measure(frame)
        hp_pct = hp_result.reading.percent if hp_result else None
        mp_pct = mp_result.reading.percent if mp_result else None

        fired = self.condition_manager.evaluate({"hp_low": hp_pct, "mp_low": mp_pct})
        self._handle_triggers(fired)

        self.runner.update()
        self.dispatcher.dispatch_pending()

        now = time.monotonic()
        if now - self._last_heartbeat >= HEARTBEAT_INTERVAL_S:
            self.link.send("PING")
            self._last_heartbeat = now

        for ack in self.link.poll_acks():
            if not ack.ok:
                print(f"\n[warn] command {ack.command_id} failed: {ack.detail}")

        return {"hp": hp_pct, "mp": mp_pct}

    def stop(self) -> None:
        """Safety stop (spec section 11): clear the queue, release
        everything on the Arduino, reset condition cooldowns."""
        self.action_queue.drain()
        try:
            self.link.send("STOP")
            deadline = time.perf_counter() + 1.0
            while time.perf_counter() < deadline:
                if any(a.ok for a in self.link.poll_acks()):
                    break
                time.sleep(0.01)
        except Exception as e:
            print(f"[warn] could not send STOP ({e}) -- relying on the Arduino's own watchdog")
        self.condition_manager.reset()

    def close(self) -> None:
        self.capture.close()
        self.link.close()


def main() -> None:
    settings = load_settings()
    print("Loading OCR model...", flush=True)
    try:
        app = MacroApp(settings)
    except WindowNotFoundError as e:
        print(f"[error] {e}", flush=True)
        sys.exit(1)

    print("Starting main loop. Ctrl+C to stop.", flush=True)
    try:
        while True:
            try:
                readings = app.tick()
            except pyserial.SerialException:
                print("\n[error] serial connection lost -- stopping safely")
                break

            hp_str = f"{readings['hp']:5.1f}%" if readings["hp"] is not None else " N/A "
            mp_str = f"{readings['mp']:5.1f}%" if readings["mp"] is not None else " N/A "
            print(
                f"\rHP={hp_str}  MP={mp_str}  queued={len(app.action_queue)}  "
                f"active_seq={app.runner.active_count}   ",
                end="",
                flush=True,  # without this, a \r-only line (no \n) can sit in the
                             # stdout buffer and never actually appear on screen in
                             # some terminals/wrappers, even though the loop is running fine
            )
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        app.stop()
        app.close()
        print("Stopped safely (queue cleared, keys/mouse released).")


if __name__ == "__main__":
    main()
