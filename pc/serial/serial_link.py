"""Serial link to the Arduino: sends "CMD <id> <TYPE> <args>" lines and
reads back "ACK <id> OK" / "ACK <id> ERR <reason>" replies.

Reading happens on a background thread so the caller's main loop is
never blocked waiting on serial I/O -- `poll_acks()` just drains
whatever responses have arrived so far and returns immediately.
"""
from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import dataclass
from typing import List, Optional

import serial


@dataclass
class AckResponse:
    command_id: int
    ok: bool
    detail: str = ""


class SerialLink:
    def __init__(self, port: str, baud_rate: int = 115200, read_timeout: float = 1.0):
        self._serial = serial.Serial(port, baud_rate, timeout=read_timeout)
        self._ack_queue: "queue.Queue[AckResponse]" = queue.Queue()
        self._id_counter = itertools.count(1)
        self._stop_event = threading.Event()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def next_command_id(self) -> int:
        return next(self._id_counter)

    def send(self, command_type: str, args: str = "") -> int:
        """Send "CMD <id> <TYPE> <args>" and return the id assigned to it."""
        cmd_id = self.next_command_id()
        line = f"CMD {cmd_id} {command_type}"
        if args:
            line += f" {args}"
        self._serial.write((line + "\n").encode("ascii"))
        return cmd_id

    def poll_acks(self) -> List[AckResponse]:
        """Drain and return all ACK responses received since the last call.

        Never blocks -- returns an empty list if nothing has arrived yet.

        Callers should still poll on a small interval (e.g. a few ms of
        sleep between calls), not in a zero-sleep tight loop: a truly
        busy `while True: poll_acks()` loop can starve the background
        reader thread of CPU time under Python's GIL, which paradoxically
        makes replies *slower* to show up here (observed 100-400ms
        latency in a zero-sleep loop vs. ~3-6ms with a 2-5ms sleep between
        checks).
        """
        acks = []
        while True:
            try:
                acks.append(self._ack_queue.get_nowait())
            except queue.Empty:
                break
        return acks

    def close(self) -> None:
        self._stop_event.set()
        self._reader_thread.join(timeout=2.0)
        self._serial.close()

    def __enter__(self) -> "SerialLink":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _read_loop(self) -> None:
        # `readline()` returns after `read_timeout` even with no data
        # (as b""), so this loop keeps checking `_stop_event` instead of
        # blocking forever on a link that's gone quiet.
        while not self._stop_event.is_set():
            try:
                raw = self._serial.readline()
            except serial.SerialException:
                break
            if not raw:
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            ack = self._parse_ack(line)
            if ack is not None:
                self._ack_queue.put(ack)

    @staticmethod
    def _parse_ack(line: str) -> Optional[AckResponse]:
        parts = line.split()
        if len(parts) < 3 or parts[0] != "ACK":
            return None
        try:
            cmd_id = int(parts[1])
        except ValueError:
            return None
        status = parts[2]
        if status == "OK":
            return AckResponse(command_id=cmd_id, ok=True)
        detail = " ".join(parts[3:]) if len(parts) > 3 else status
        return AckResponse(command_id=cmd_id, ok=False, detail=detail)
