"""Evaluates all configured HP/MP conditions against the latest gauge
readings and reports which ones fired this poll.

HP and MP conditions are fully independent -- each has its own
Condition instance with its own cooldown, so one being on cooldown never
blocks or delays the other from firing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from pc.condition.condition import Condition


@dataclass
class TriggeredAction:
    condition_name: str
    key: str


class ConditionManager:
    def __init__(self, conditions: List[Condition], keys: Dict[str, str]):
        """
        Args:
            conditions: the conditions to evaluate, in order.
            keys: condition name -> key to send when it fires (e.g.
                {"hp_low": "F1", "mp_low": "F2"}), read from config so
                no key binding is hardcoded here.
        """
        self._conditions = conditions
        self._keys = keys

    def evaluate(self, readings: Dict[str, Optional[float]]) -> List[TriggeredAction]:
        """`readings` maps condition name -> current percent (or None).

        Returns the actions that should fire this poll -- at most one
        per condition, since each condition enforces its own cooldown.
        """
        fired = []
        for condition in self._conditions:
            percent = readings.get(condition.name)
            if condition.check(percent):
                fired.append(TriggeredAction(condition_name=condition.name, key=self._keys[condition.name]))
        return fired

    def reset(self) -> None:
        """Clear all conditions' cooldowns."""
        for condition in self._conditions:
            condition.reset()
