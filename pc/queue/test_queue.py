"""Manual test for development Step 8: Event Queue.

Usage (run from the project root, with the venv active):

    python -m pc.queue.test_queue

Uses PING for every command in this test (no real keyboard/mouse
output) since the point here is the queueing/dispatch mechanics, not
HID output -- that was already verified in Steps 6-7.

Two checks:
1. Arduino-side receive queue: fire a burst of PINGs with no pacing
   between sends. Before this step, SerialProtocol held only a single
   pending command -- if two full lines arrived before loop() drained
   it, the second would silently overwrite the first. This proves
   that's fixed (every PING in the burst gets its own ACK).
2. PC-side ActionQueue + ActionDispatcher: push two actions onto the
   queue back-to-back (simulating HP and MP both tripping their
   threshold in the same poll, per the spec's own example) and confirm
   both get dispatched and acknowledged, in the order they were queued.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from pc.config.config_loader import load_settings  # noqa: E402
from pc.serial.serial_link import AckResponse, SerialLink  # noqa: E402
from pc.serial.port_finder import resolve_port  # noqa: E402
from pc.queue.action_queue import ActionQueue, QueuedAction  # noqa: E402
from pc.queue.dispatcher import ActionDispatcher  # noqa: E402


def _collect_acks(link: SerialLink, expected_ids: Iterable[int], timeout: float = 3.0) -> Tuple[Dict[int, AckResponse], Set[int]]:
    remaining = set(expected_ids)
    results: Dict[int, AckResponse] = {}
    deadline = time.perf_counter() + timeout
    while remaining and time.perf_counter() < deadline:
        for ack in link.poll_acks():
            if ack.command_id in remaining:
                results[ack.command_id] = ack
                remaining.discard(ack.command_id)
        time.sleep(0.005)  # yield -- see serial_link.py's note on tight busy-loops
    return results, remaining


def test_burst_no_loss(link: SerialLink) -> None:
    print("-- Burst test: 10 PINGs sent back-to-back, no pacing --")
    ids = [link.send("PING") for _ in range(10)]
    results, missing = _collect_acks(link, ids)
    print(f"  sent={len(ids)} acked={len(results)} missing={sorted(missing)}")
    if missing:
        print("  [FAIL] some commands never got a reply -- the receive queue lost them")
    else:
        print("  [OK] all 10 acknowledged -- no command was overwritten/dropped")


def test_action_queue(link: SerialLink) -> None:
    print("\n-- ActionQueue test: simulate HP and MP tripping in the same poll --")
    action_queue = ActionQueue()
    action_queue.push(QueuedAction(source="hp_low", command_type="PING"))
    action_queue.push(QueuedAction(source="mp_low", command_type="PING"))
    dispatcher = ActionDispatcher(action_queue, link)

    sent = dispatcher.dispatch_pending()
    print(f"  dispatched {len(sent)} action(s): {[(r.action.source, r.command_id) for r in sent]}")

    ids = [r.command_id for r in sent]
    results, missing = _collect_acks(link, ids)
    for r in sent:
        ack = results.get(r.command_id)
        status = ("OK" if ack.ok else f"ERR {ack.detail}") if ack else "[no ACK]"
        print(f"  {r.action.source} -> {r.action.command_type} {r.action.args}: {status}")

    if missing:
        print("  [FAIL] some dispatched actions never got a reply")
    else:
        print("  [OK] both actions acknowledged")

    print(f"  queue length after dispatch: {len(action_queue)} (expect 0)")


def main() -> None:
    settings = load_settings()
    serial_cfg = settings["serial"]
    with SerialLink(resolve_port(serial_cfg["port"]), serial_cfg["baud_rate"]) as link:
        time.sleep(2.5)  # Leonardo boot delay after port open
        link.send("PING")
        time.sleep(0.3)
        link.poll_acks()

        test_burst_no_loss(link)
        test_action_queue(link)


if __name__ == "__main__":
    main()
