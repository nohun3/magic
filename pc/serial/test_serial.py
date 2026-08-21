"""Manual test for development Step 5: Arduino serial communication.

Usage (run from the project root, with the venv active):

    python -m pc.serial.test_serial

Sends a handful of PING commands and waits for their ACKs, printing
round-trip latency for each. Confirms the wire protocol
("CMD <id> <TYPE> ..." / "ACK <id> ...") works end-to-end against the
real board before any keyboard/mouse actions are added (Step 6+).
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


def main() -> None:
    settings = load_settings()
    serial_cfg = settings["serial"]
    port = resolve_port(serial_cfg["port"])
    print(f"Connecting to {port} @ {serial_cfg['baud_rate']}...")

    with SerialLink(port, serial_cfg["baud_rate"]) as link:
        # Opening the port resets a Leonardo (native USB) -- give the
        # sketch a moment to boot, then send one throwaway PING and
        # drain it so the boot/enumeration delay doesn't pollute the
        # timed readings below.
        time.sleep(2.5)
        link.send("PING")
        time.sleep(0.5)
        link.poll_acks()

        # Send one at a time, each waiting for its own ACK before the
        # next is sent -- gives a clean per-command RTT instead of a
        # batch of sends whose replies arrive together.
        acked = 0
        for _ in range(5):
            t0 = time.perf_counter()
            cmd_id = link.send("PING")
            got = False
            while time.perf_counter() - t0 < 2.0:
                for ack in link.poll_acks():
                    if ack.command_id == cmd_id:
                        rtt_ms = (time.perf_counter() - t0) * 1000
                        status = "OK" if ack.ok else f"ERR {ack.detail}"
                        print(f"id={cmd_id} {status} rtt={rtt_ms:.1f}ms")
                        got = True
                        acked += 1
                if got:
                    break
                time.sleep(0.005)  # yield -- a tight busy-loop can starve the reader thread
            if not got:
                print(f"id={cmd_id} [warn] no ACK within 2s")

        if acked == 5:
            print("All PINGs acknowledged.")

        # Also confirm an unknown command type gets a distinct error
        # reply rather than silence or a crash.
        unknown_id = link.send("BOGUS")
        deadline = time.perf_counter() + 2.0
        got_reply = False
        while time.perf_counter() < deadline:
            for ack in link.poll_acks():
                if ack.command_id == unknown_id:
                    print(f"Unknown-type check: id={ack.command_id} ok={ack.ok} detail={ack.detail!r}")
                    got_reply = True
            if got_reply:
                break
            time.sleep(0.05)
        if not got_reply:
            print("[warn] no reply to the unknown-type command")


if __name__ == "__main__":
    main()
