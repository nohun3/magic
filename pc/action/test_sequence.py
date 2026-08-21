"""Manual test for development Step 9: Action Sequence.

Usage (run from the project root, with the venv active):

    python -m pc.action.test_sequence unit    # no hardware: step conversion + config parsing
    python -m pc.action.test_sequence timing  # hardware: verify non-blocking WAIT timing over real serial (PING only, no HID output)
    python -m pc.action.test_sequence full    # both (default)

`unit` checks step_to_command()'s output for each step type and that
settings.yaml's `sequences.hp_low_example` (mirroring the spec's own
"move, click, F1, F2" example) parses correctly -- purely in-process,
no Arduino needed.

`timing` runs a real sequence through SequenceRunner -> ActionQueue ->
ActionDispatcher -> SerialLink against the actual board, using PING for
every step (so nothing visible happens) but checking the *measured*
gaps between each step's dispatch against its WAIT duration, and
confirming the main loop never blocks (measured via loop iteration
count while the sequence is in flight).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.serial.serial_link import SerialLink  # noqa: E402
from pc.serial.port_finder import resolve_port  # noqa: E402
from pc.queue.action_queue import ActionQueue, QueuedAction  # noqa: E402
from pc.queue.dispatcher import ActionDispatcher  # noqa: E402
from pc.action.action_sequence import (  # noqa: E402
    ActionSequence, KeyStep, MouseClickStep, MouseMoveStep, SequenceRunner, WaitStep, step_to_command,
)
from pc.action.sequence_config import load_all_sequences  # noqa: E402


def run_unit_checks() -> bool:
    print("-- step_to_command() --")
    cases = [
        (KeyStep(key="F1", hold_ms=30), ("KEY", "F1 30")),
        (MouseMoveStep(x=100, y=200), ("MOUSE_MOVE", "100 200")),
        (MouseClickStep(button="LEFT", hold_ms=25), ("MOUSE_CLICK", "LEFT 25")),
        (WaitStep(ms=50), None),
    ]
    ok = True
    for step, expected in cases:
        actual = step_to_command(step)
        status = "OK" if actual == expected else "FAIL"
        if actual != expected:
            ok = False
        print(f"  {step!r} -> {actual} (expected {expected}) [{status}]")

    print("\n-- sequences.hp_low_example config parsing --")
    settings = load_settings()
    sequences = load_all_sequences(settings)
    if "hp_low_example" not in sequences:
        print("  [FAIL] hp_low_example not found in settings.yaml")
        return False
    seq = sequences["hp_low_example"]
    print(f"  parsed {len(seq.steps)} steps:")
    for step in seq.steps:
        print(f"    {step!r}")
    expected_types = [MouseMoveStep, WaitStep, MouseClickStep, WaitStep, KeyStep, WaitStep, KeyStep]
    actual_types = [type(s) for s in seq.steps]
    if actual_types != expected_types:
        print(f"  [FAIL] step type sequence mismatch: {actual_types} != {expected_types}")
        ok = False
    else:
        print("  [OK] step types match the spec's move/wait/click/wait/key/wait/key example")
    return ok


def run_timing_check() -> None:
    settings = load_settings()
    serial_cfg = settings["serial"]

    with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
        time.sleep(2.5)  # Leonardo boot delay after port open
        link.send("PING")
        time.sleep(0.3)
        link.poll_acks()

        action_queue = ActionQueue()
        dispatcher = ActionDispatcher(action_queue, link)

        dispatch_log = []  # (t, command_type, args)

        def dispatch_fn(command_type: str, args: str) -> None:
            # Sequence steps are meant to go through the queue like any
            # other action -- swap in PING so this test has no visible
            # side effects, but keep it going through the real queue.
            dispatch_log.append((time.monotonic(), command_type, args))
            action_queue.push(QueuedAction(source="test_sequence", command_type="PING"))

        runner = SequenceRunner(dispatch_fn)

        sequence = ActionSequence(
            name="timing_test",
            steps=[
                KeyStep(key="F1"),       # t=0
                WaitStep(ms=100),
                KeyStep(key="F2"),       # t=~100ms
                WaitStep(ms=200),
                MouseClickStep(button="LEFT"),  # t=~300ms
            ],
        )

        print("-- Running a 3-step sequence with 100ms/200ms waits (PING substituted for real output) --")
        start = time.monotonic()
        runner.start(sequence)

        loop_iterations = 0
        sent_ids = []
        while runner.active_count > 0 or len(action_queue) > 0:
            runner.update()
            sent_ids.extend(r.command_id for r in dispatcher.dispatch_pending())
            loop_iterations += 1
            if loop_iterations > 200_000:  # safety valve against an infinite loop bug
                print("  [FAIL] runner never finished")
                break

        print(f"  loop iterations while sequence was active: {loop_iterations} (never blocked/slept)")
        print(f"  dispatched {len(dispatch_log)} step(s):")
        prev_t = start
        expected_gaps_ms = [0, 100, 200]
        ok = True
        for i, (t, cmd_type, args) in enumerate(dispatch_log):
            gap_ms = (t - prev_t) * 1000
            expected = expected_gaps_ms[i] if i < len(expected_gaps_ms) else None
            note = ""
            if expected is not None:
                error_ms = gap_ms - expected
                note = f" (expected ~{expected}ms, error {error_ms:+.1f}ms)"
                if abs(error_ms) > 30:  # generous tolerance -- this is a polled loop, not a hard real-time system
                    ok = False
                    note += " [FAIL]"
            print(f"    step {i}: {cmd_type} {args} at +{gap_ms:.1f}ms{note}")
            prev_t = t

        # Confirm every dispatched step's substituted PING actually got acknowledged.
        results = {}
        deadline = time.perf_counter() + 3.0
        remaining = set(sent_ids)
        while remaining and time.perf_counter() < deadline:
            for ack in link.poll_acks():
                if ack.command_id in remaining:
                    results[ack.command_id] = ack
                    remaining.discard(ack.command_id)
            time.sleep(0.005)
        print(f"  acked {len(results)}/{len(sent_ids)} dispatched commands")

        if ok and not remaining:
            print("  [OK] sequence timing and delivery both look correct")
        else:
            print("  [FAIL] see above")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode not in ("unit", "timing", "full"):
        print(f"Unknown mode: {mode!r} (use 'unit', 'timing', or 'full')")
        sys.exit(1)

    if mode in ("unit", "full"):
        run_unit_checks()
    if mode in ("timing", "full"):
        print()
        run_timing_check()


if __name__ == "__main__":
    main()
