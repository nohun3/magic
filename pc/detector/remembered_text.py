"""Finds a piece of text inside a dialog's content region via OCR only
the *first* time it's asked, then remembers where it was (as an offset
from the dialog's content_region top-left) and trusts that position
forever after -- same "locate once, cache forever" pattern as
SkillPanelLocator/roi_skill/roi_buff (see skill_panel.py's docstring),
just applied to an OCR-derived text position instead of a
template-matched one.

Why this is safe to do: a given dialog's menu/list layout is
deterministic between separate openings of the *same* dialog (e.g.
"[오렌] 여관" is always the same list row in the talking-scroll dialog,
"방을 대여한다" is always the same NPC-menu row, "OK" is always the same
confirm-button position) -- unlike HP/MP or roi_skill's icons, this text
isn't expected to move around or change between one open of the dialog
and the next. OCR (hundreds of ms to ~4s) only has to pay for itself
once per RememberedDialogText instance (i.e. once per process run, since
that's this object's lifetime -- same as every other "locate once"
cache in this codebase); every call after that is just the cheap
border-anchor template match (not OCR) to re-derive the dialog's current
*absolute* frame position, plus the cached relative offset.

If the layout ever legitimately changes (different dialog reused for
different content at a different scroll position, etc.), the cache goes
stale silently -- there's no re-verification, by design, matching
skill_panel.py's same tradeoff. Construct a fresh instance to reset it.

That tradeoff isn't safe everywhere, though -- confirmed live with
step_move_to_wasteland.py's gate_dest_text: the border-anchor match
(content_region() succeeding) only proves *some* dialog is open, not
that it's showing the content the cached offset was measured against.
When the click that's supposed to open a fresh dialog is itself
low-confidence (there, a teleport_gate template match that can land on
a false positive), a stale *different* dialog can still be open from an
earlier step, and this class would happily hand back a location that
was never re-verified against it. Pass `cache=False` for a selector
that follows a step like that -- it costs an OCR pass every call
instead of once, but that's cheap here (~800ms with the yellow-text
preprocessing) next to being wrong.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import numpy as np

from pc.capture.screen_capture import Region
from pc.detector.chat_reader import KoreanTextReader
from pc.detector.window_content import WindowContentLocator

MatchFn = Callable[[str], bool]
# Takes the full (text, box) list from one OCR pass -- not just one line
# at a time -- so a selector can reason about more than one line (e.g.
# "the '버림받은' line that does NOT have a '심연' line near it", see
# step_move_to_wasteland.py's _select_wasteland_gate_destination()).
SelectorFn = Callable[[List[Tuple[str, Region]]], Optional[Region]]


def first_matching(match_fn: MatchFn) -> SelectorFn:
    """Adapts a single-line predicate (e.g. from needles_match_fn()/
    exact_match_fn() in chat_reader.py) into a SelectorFn -- the common
    case, one line either matches or it doesn't, no cross-line reasoning
    needed."""
    def select(lines: List[Tuple[str, Region]]) -> Optional[Region]:
        for text, box in lines:
            if match_fn(text):
                return box
        return None
    return select


class RememberedDialogText:
    def __init__(self, content_locator: WindowContentLocator, reader: KoreanTextReader, selector: SelectorFn,
                 preprocess: Optional[Callable[[np.ndarray], np.ndarray]] = None, cache: bool = True):
        """`preprocess`, if given, runs on the content crop before OCR --
        e.g. pc/detector/color_mask.py's mask_non_yellow() to blank out
        everything except a dialog's yellow "action" text, which cut OCR
        time ~10x on the post-gate confirm dialogs in
        step_move_to_wasteland.py (see that module) by giving the
        detector far less to find/recognize. Only safe where the target
        text is reliably that color and nothing else nearby is -- not
        applied to plain-white dialog text (see that module for which is
        which).

        `cache=False` disables the "locate once, trust forever" behavior
        (re-runs OCR every find() call instead) -- see the class
        docstring for when that's necessary rather than just slower."""
        self._content_locator = content_locator
        self._reader = reader
        self._selector = selector
        self._preprocess = preprocess
        self._cache_enabled = cache
        self._cached_offset: Optional[Region] = None  # relative to content_region's top-left

    def find(self, frame: np.ndarray) -> Optional[Region]:
        """Full-frame-pixel-coordinate Region of the matched text, or
        None if the dialog isn't open, or the selector didn't find
        anything in it (with caching on, that miss is only possible on
        the very first call; with caching off, every call re-runs the
        selector and can miss)."""
        content_region = self._content_locator.content_region(frame)
        if content_region is None:
            return None

        if self._cache_enabled and self._cached_offset is not None:
            off = self._cached_offset
        else:
            crop = self._content_locator.crop_content(frame)
            if crop is None:
                return None
            if self._preprocess is not None:
                crop = self._preprocess(crop)
            off = self._selector(self._reader.read_lines_with_boxes(crop))
            if off is None:
                return None
            if self._cache_enabled:
                self._cached_offset = off

        return Region(
            left=content_region.left + off.left,
            top=content_region.top + off.top,
            width=off.width,
            height=off.height,
        )
