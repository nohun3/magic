"""Loads ActionSequence definitions out of settings.yaml so sequences
(and the wait between each of their steps) are configurable, not
hardcoded -- see the `sequences:` section of pc/config/settings.yaml.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pc.action.action_sequence import ActionSequence, KeyStep, MouseClickStep, MouseMoveStep, Step, WaitStep

_STEP_BUILDERS = {
    "KEY": lambda s: KeyStep(key=s["key"], hold_ms=s.get("hold_ms", 30)),
    "MOUSE_MOVE": lambda s: MouseMoveStep(x=s["x"], y=s["y"]),
    "MOUSE_CLICK": lambda s: MouseClickStep(button=s["button"], hold_ms=s.get("hold_ms", 30)),
    "WAIT": lambda s: WaitStep(ms=s["ms"]),
}


def _build_step(raw: Dict[str, Any]) -> Step:
    step_type = raw.get("type")
    builder = _STEP_BUILDERS.get(step_type)
    if builder is None:
        raise ValueError(f"Unknown sequence step type: {step_type!r} (expected one of {sorted(_STEP_BUILDERS)})")
    return builder(raw)


def load_sequence(name: str, raw_steps: List[Dict[str, Any]]) -> ActionSequence:
    return ActionSequence(name=name, steps=[_build_step(s) for s in raw_steps])


def load_all_sequences(settings: Dict[str, Any]) -> Dict[str, ActionSequence]:
    """Parse every sequence under settings["sequences"], keyed by name."""
    raw = settings.get("sequences", {})
    return {name: load_sequence(name, steps) for name, steps in raw.items()}
