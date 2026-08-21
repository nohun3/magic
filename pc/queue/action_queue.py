"""FIFO queue of pending actions waiting to be sent to the Arduino.

`ConditionManager.evaluate()` can return multiple triggered actions from
a single poll (e.g. HP and MP both crossing their thresholds together --
see the spec's own "HP condition -> F1, simultaneously MP condition ->
F2" example). Pushing them through a real queue instead of sending them
ad hoc guarantees they're dispatched in a fixed order and none get
silently dropped or overwritten -- the PC-side equivalent of the
Arduino-side receive queue in SerialProtocol.
"""
from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class QueuedAction:
    source: str          # e.g. condition name, for logging/debugging
    command_type: str    # e.g. "KEY"
    args: str = ""        # e.g. "F1"


class ActionQueue:
    def __init__(self):
        self._queue: "queue.Queue[QueuedAction]" = queue.Queue()

    def push(self, action: QueuedAction) -> None:
        self._queue.put(action)

    def pop(self) -> Optional[QueuedAction]:
        """Non-blocking pop; returns None if empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def drain(self) -> List[QueuedAction]:
        """Pop everything currently queued, in order."""
        items = []
        while True:
            item = self.pop()
            if item is None:
                break
            items.append(item)
        return items

    def __len__(self) -> int:
        return self._queue.qsize()
