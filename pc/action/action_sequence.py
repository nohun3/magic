"""Action Sequences: an ordered list of steps (key taps, mouse move/click,
waits) that fire together from a single condition -- e.g. the spec's own
example:

    HP <= 30%
    -> Mouse Move
    -> Left Click
    -> F1
    -> F2

expressed as steps with explicit gaps:

    MOVE
    WAIT 30ms
    CLICK
    WAIT 50ms
    F1
    WAIT 100ms
    F2

`SequenceRunner` executes these non-blocking: it's driven by repeated
`update()` calls (time.monotonic()-based, like everything else in this
project), never `time.sleep()`. Multiple sequences can be in flight at
once -- e.g. hp_low and mp_low both firing close together -- each
advancing independently at its own pace.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Union


@dataclass
class KeyStep:
    key: str
    hold_ms: int = 30


@dataclass
class MouseMoveStep:
    x: int
    y: int


@dataclass
class MouseClickStep:
    button: str
    hold_ms: int = 30


@dataclass
class WaitStep:
    ms: int


Step = Union[KeyStep, MouseMoveStep, MouseClickStep, WaitStep]


@dataclass
class ActionSequence:
    name: str
    steps: List[Step]


def step_to_command(step: Step) -> Optional[Tuple[str, str]]:
    """Return (command_type, args) for a step, or None for a WaitStep
    (it doesn't send anything -- it only delays the next step)."""
    if isinstance(step, KeyStep):
        return "KEY", f"{step.key} {step.hold_ms}"
    if isinstance(step, MouseMoveStep):
        return "MOUSE_MOVE", f"{step.x} {step.y}"
    if isinstance(step, MouseClickStep):
        return "MOUSE_CLICK", f"{step.button} {step.hold_ms}"
    if isinstance(step, WaitStep):
        return None
    raise TypeError(f"Unknown step type: {type(step)!r}")


DispatchFn = Callable[[str, str], None]


@dataclass
class _ActiveSequence:
    sequence: ActionSequence
    next_index: int = 0
    next_due: float = field(default_factory=time.monotonic)


class SequenceRunner:
    """Non-blocking runner for one or more in-flight ActionSequences.

    `dispatch_fn(command_type, args)` is called for each non-WAIT step
    when it comes due -- typically something that pushes onto an
    ActionQueue (see pc/queue/) rather than sending directly, so
    sequence output still goes through the same no-loss queue as any
    other action.
    """

    def __init__(self, dispatch_fn: DispatchFn):
        self._dispatch_fn = dispatch_fn
        self._active: List[_ActiveSequence] = []

    def start(self, sequence: ActionSequence) -> None:
        self._active.append(_ActiveSequence(sequence=sequence))

    def update(self) -> None:
        """Call every tick. Advances whichever sequences have a step
        due; never blocks or sleeps."""
        now = time.monotonic()
        still_active = []
        for active in self._active:
            self._advance(active, now)
            if active.next_index < len(active.sequence.steps):
                still_active.append(active)
        self._active = still_active

    def _advance(self, active: _ActiveSequence, now: float) -> None:
        steps = active.sequence.steps
        # Process every step that's already due in this one update()
        # call -- a WAIT just pushes next_due into the future (loop
        # exits then); a dispatched step's next_due is "now", so a run
        # of steps with no WAIT between them all fire in the same tick
        # instead of trickling out one per update() call.
        while active.next_index < len(steps) and now >= active.next_due:
            step = steps[active.next_index]
            if isinstance(step, WaitStep):
                active.next_due = now + step.ms / 1000.0
            else:
                command = step_to_command(step)
                if command is not None:
                    self._dispatch_fn(*command)
                active.next_due = now
            active.next_index += 1

    @property
    def active_count(self) -> int:
        return len(self._active)
