"""Drains an ActionQueue and dispatches each action to the Arduino over
the serial link.

Doesn't wait for a reply before sending the next queued action -- it
doesn't need to, since SerialLink tracks ACKs independently by command
id and the Arduino now has its own receive queue (see
arduino/libraries/SerialProtocol), so sending a burst here is safe and
nothing gets overwritten on either side.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from pc.queue.action_queue import ActionQueue, QueuedAction
from pc.serial.serial_link import SerialLink


@dataclass
class DispatchRecord:
    command_id: int
    action: QueuedAction


class ActionDispatcher:
    def __init__(self, action_queue: ActionQueue, link: SerialLink):
        self._queue = action_queue
        self._link = link

    def dispatch_pending(self) -> List[DispatchRecord]:
        """Send every action currently queued, in order. Returns what was sent."""
        sent = []
        for action in self._queue.drain():
            cmd_id = self._link.send(action.command_type, action.args)
            sent.append(DispatchRecord(command_id=cmd_id, action=action))
        return sent
