"""Build Persian subtitle cues from word-level transcription output.

Sits between a transcriber and the Persian Remotion composition. Its input is a
flat list of timed words; its output is the `cues` array the composition consumes,
with word timings preserved so karaoke emphasis tracks the voice.

## The one decision this module makes

Where to end each cue. Everything else is bookkeeping. A cue that is too long
outruns the reader; one that is too short flickers; one that ends mid-clause reads
as an error even when the timing is perfect. Three limits shape the grouping, and
the reasoning for each is worth stating because they conflict:

* **Clause boundaries.** Persian punctuation («،» «؛» «.» «؟») marks a place the
  reader already expects to pause, so a cue ending there costs nothing. Splitting
  a clause in half costs a lot even when both halves fit every other limit.

* **Extent** (`MAX_CUE_SECONDS`, `MAX_CUE_VISIBLE_CHARS`). Past roughly six seconds
  a single cue loses the reader's thread, and past 84 visible characters the glass
  panel runs out of room and the renderer starts shrinking type.

* **Minimum on-screen time** (`MIN_CUE_SECONDS`). Below roughly a second, a cue
  registers as a flash rather than text. Two short clauses are merged rather than
  shown as two cues.

**Reading speed** (`MAX_CPS`, 21 visible chars/second) is enforced differently — by
`audit_cues`, after the fact, rather than during grouping. The reason is that density
is essentially invariant under grouping: adding a word to a cue adds both its
characters and its spoken duration, so every cue converges on the narration's own
rate. If the narration is faster than the ceiling, no grouping can fix it, and a
density veto during grouping would emit one word per cue — over-speed *and* below the
minimum duration, which is strictly worse. Over-speed is a property of the script and
the delivery, and the honest remedy is to shorten the script.

Visible length is measured with `visible_length`, so ZWNJ and combining marks are not
charged: «می‌روم» costs 5, not 6.

## What this module deliberately does *not* do

It does not decide line breaks. Those depend on the pixel width of Estedad at the
chosen size, which only the renderer can measure. Splitting the work here would
mean guessing at widths and being wrong. See `remotion-composer/src/persian/layout.ts`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from lib.persian_text import (
    normalize,
    to_persian_digits,
    visible_length,
)

#: Reading-speed ceiling in visible characters per second. Mirrors `MAX_CPS` in
#: `remotion-composer/src/persian/tokens.ts`; a contract test pins them together.
MAX_CPS = 21.0

#: Below this, a cue reads as a flash rather than as text.
MIN_CUE_SECONDS = 1.0

#: Above this, even a fast reader loses the thread of a single cue.
MAX_CUE_SECONDS = 6.0

#: Hard ceiling on visible characters per cue, independent of duration. A cue can
#: satisfy MAX_CPS by simply being long, but past this the *panel* runs out of
#: room and the renderer's fitter starts shrinking type.
MAX_CUE_VISIBLE_CHARS = 84

#: Persian clause terminators, strongest first. A cue prefers to end on the
#: strongest boundary available inside its budget.
_STRONG_TERMINATORS = (".", "؟", "!", "…")
_WEAK_TERMINATORS = ("،", "؛", ":")

#: Gap between consecutive cues, seconds. Small enough to be imperceptible, large
#: enough that two adjacent cues never occupy the same frame — which would render
#: two glass panels stacked on top of each other.
CUE_GAP_SECONDS = 0.001


@dataclass
class TimedWord:
    """One word with its spoken window."""

    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class PersianCue:
    """One subtitle cue, ready for the composition's `cues` array."""

    id: str
    text: str
    start_seconds: float
    end_seconds: float
    words: list[dict[str, Any]] = field(default_factory=list)
    highlight_phrases: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    @property
    def cps(self) -> float:
        """Visible characters per second. The reading-speed metric."""
        if self.duration <= 0:
            return float("inf")
        return visible_length(self.text) / self.duration

    def to_props(self) -> dict[str, Any]:
        """The JSON shape `PersianCue` expects in the renderer."""
        props: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "startSeconds": round(self.start_seconds, 3),
            "endSeconds": round(self.end_seconds, 3),
        }
        if self.words:
            props["words"] = self.words
        if self.highlight_phrases:
            props["highlightPhrases"] = self.highlight_phrases
        return props


def _terminator_rank(word: str) -> int:
    """3 for a strong clause end, 2 for a weak one, 0 otherwise."""
    stripped = normalize(word).rstrip()
    if stripped.endswith(_STRONG_TERMINATORS):
        return 3
    if stripped.endswith(_WEAK_TERMINATORS):
        return 2
    return 0


def _fits(words: list[TimedWord], extra: TimedWord) -> bool:
    """Whether `extra` can join `words` without breaking an actionable limit.

    Only the two limits that **grouping can actually influence** are checked here:
    total on-screen duration, and the character ceiling that would force the renderer
    to shrink type. Both bind on the group's own extent, so breaking earlier genuinely
    fixes them.

    Reading speed is deliberately *not* checked here, and that is worth explaining
    because it looks like an omission.

    Density is very nearly invariant under grouping: adding a word adds both its
    characters and its spoken duration, so a cue's chars/second converges on the
    narration's own rate. When the narration is faster than the 21 chars/second
    ceiling, no grouping satisfies it — but a density check here would still veto every
    join, emitting one word per cue. Those cues are over-speed *and* below the
    minimum duration: strictly worse than packing normally.

    So density is reported by `audit_cues` instead, where it belongs: it is a property
    of the script and the narration, fixable only by shortening the script or slowing
    the delivery.
    """
    candidate = words + [extra]
    text = " ".join(w.text for w in candidate)
    duration = candidate[-1].end - candidate[0].start

    if duration > MAX_CUE_SECONDS:
        return False
    if visible_length(text) > MAX_CUE_VISIBLE_CHARS:
        return False
    return True


def build_cues(
    words: Iterable[dict[str, Any]],
    *,
    persian_digits: bool = True,
    id_prefix: str = "cue",
) -> list[PersianCue]:
    """Group timed words into readable Persian cues.

    Args:
        words: Word entries as emitted by either transcriber — each needs
            `word`/`text`, `start`, and `end`. Both key spellings are accepted so
            the caller does not have to know which provider ran.
        persian_digits: Convert ASCII and Arabic-Indic digits to Persian-Indic.
            On by default: a Persian video showing Western digits looks unfinished,
            and the conversion is safe because only digit glyphs are substituted.
        id_prefix: Prefix for generated cue IDs.

    Returns:
        Cues in timeline order. Never overlapping, never shorter than
        `MIN_CUE_SECONDS` unless the source audio itself is that short.

    Raises:
        ValueError: if a word entry lacks usable timing. Silently dropping it
            would shift every subsequent cue's timing by that word's duration,
            producing subtitles that drift out of sync with no visible cause.
    """
    parsed: list[TimedWord] = []
    for index, raw in enumerate(words):
        text = raw.get("word", raw.get("text"))
        if text is None:
            raise ValueError(f"word entry {index} has neither 'word' nor 'text': {raw!r}")
        if "start" not in raw or "end" not in raw:
            raise ValueError(f"word entry {index} is missing start/end: {raw!r}")

        cleaned = normalize(str(text)).strip()
        if not cleaned:
            continue
        if persian_digits:
            cleaned = to_persian_digits(cleaned)

        parsed.append(
            TimedWord(text=cleaned, start=float(raw["start"]), end=float(raw["end"]))
        )

    if not parsed:
        return []

    groups = _group_words(parsed)
    groups = _merge_short_groups(groups)

    cues: list[PersianCue] = []
    for index, group in enumerate(groups):
        start = group[0].start
        end = group[-1].end
        # Trim the tail so consecutive cues never share a frame. Without this two
        # glass panels can be on screen simultaneously for one frame, which reads
        # as a flicker.
        if index + 1 < len(groups):
            end = min(end, groups[index + 1][0].start - CUE_GAP_SECONDS)
        end = max(end, start + 0.05)

        cues.append(
            PersianCue(
                id=f"{id_prefix}-{index + 1}",
                text=" ".join(w.text for w in group),
                start_seconds=start,
                end_seconds=end,
                words=[
                    {
                        "text": w.text,
                        "startSeconds": round(w.start, 3),
                        "endSeconds": round(w.end, 3),
                    }
                    for w in group
                ],
            )
        )

    return cues


def _group_words(words: list[TimedWord]) -> list[list[TimedWord]]:
    """Greedily accumulate words, breaking at the best boundary in budget.

    Greedy rather than a global optimization, because cue boundaries have to
    respect the audio: a cue cannot be moved earlier to balance a later one, since
    its start is fixed by when its first word is spoken. That removes the
    freedom a global optimizer would need, so the added complexity buys nothing.
    """
    groups: list[list[TimedWord]] = []
    current: list[TimedWord] = []
    # Index within `current` of the best clause boundary seen so far, and its rank.
    best_break: Optional[int] = None
    best_rank = 0

    for word in words:
        if current and not _fits(current, word):
            # Over budget. Break at the strongest clause boundary found, or at the
            # last word if the whole span has no punctuation at all.
            if best_break is not None and best_break < len(current) - 1:
                groups.append(current[: best_break + 1])
                current = current[best_break + 1 :]
            else:
                groups.append(current)
                current = []
            best_break = None
            best_rank = 0

            # Recompute the boundary state for the words carried over.
            for offset, carried in enumerate(current):
                rank = _terminator_rank(carried.text)
                if rank >= best_rank and rank > 0:
                    best_rank = rank
                    best_break = offset

        current.append(word)
        rank = _terminator_rank(word.text)
        # `>=` so a later boundary of equal strength wins: breaking as late as the
        # budget allows produces fuller cues and fewer of them.
        if rank > 0 and rank >= best_rank:
            best_rank = rank
            best_break = len(current) - 1

        # A strong terminator that already satisfies the minimum duration is the
        # natural end of a cue — take it rather than packing more in.
        if rank == 3 and (current[-1].end - current[0].start) >= MIN_CUE_SECONDS:
            groups.append(current)
            current = []
            best_break = None
            best_rank = 0

    if current:
        groups.append(current)

    return groups


def _merge_short_groups(groups: list[list[TimedWord]]) -> list[list[TimedWord]]:
    """Fold away cues too brief to read, when the merge still fits the budget.

    A sub-second cue is a flash. Merging forward is preferred (the following cue
    has not been seen yet, so extending into it is invisible to the viewer);
    merging backward is the fallback for a short final cue.
    """
    if len(groups) <= 1:
        return groups

    merged: list[list[TimedWord]] = []
    index = 0
    while index < len(groups):
        group = groups[index]
        duration = group[-1].end - group[0].start

        if duration >= MIN_CUE_SECONDS or index == len(groups) - 1:
            merged.append(group)
            index += 1
            continue

        nxt = groups[index + 1]
        combined = group + nxt
        text = " ".join(w.text for w in combined)
        combined_duration = combined[-1].end - combined[0].start

        if (
            visible_length(text) <= MAX_CUE_VISIBLE_CHARS
            and combined_duration <= MAX_CUE_SECONDS
        ):
            merged.append(combined)
            index += 2
        else:
            # Cannot merge without breaking a hard limit. Keep the short cue: a
            # brief cue is a lesser fault than an unreadable one.
            merged.append(group)
            index += 1

    # A short final cue merges backward, since there is nothing ahead of it.
    if len(merged) >= 2:
        last = merged[-1]
        if (last[-1].end - last[0].start) < MIN_CUE_SECONDS:
            combined = merged[-2] + last
            text = " ".join(w.text for w in combined)
            if visible_length(text) <= MAX_CUE_VISIBLE_CHARS:
                merged = merged[:-2] + [combined]

    return merged


def audit_cues(cues: list[PersianCue]) -> list[str]:
    """Report every cue that violates a readability limit.

    Returned as human-readable strings for the reviewer stage to surface. Empty
    means the cue set is within budget on every axis.
    """
    problems: list[str] = []
    for cue in cues:
        if cue.cps > MAX_CPS:
            problems.append(
                f"{cue.id}: {cue.cps:.1f} chars/sec exceeds the {MAX_CPS} ceiling "
                f"({visible_length(cue.text)} visible chars in {cue.duration:.2f}s)"
            )
        if visible_length(cue.text) > MAX_CUE_VISIBLE_CHARS:
            problems.append(
                f"{cue.id}: {visible_length(cue.text)} visible chars exceeds "
                f"{MAX_CUE_VISIBLE_CHARS} — the renderer will shrink the type"
            )
        if cue.duration < MIN_CUE_SECONDS:
            problems.append(
                f"{cue.id}: on screen for {cue.duration:.2f}s, below the "
                f"{MIN_CUE_SECONDS}s minimum — reads as a flash"
            )
        if cue.duration > MAX_CUE_SECONDS:
            problems.append(
                f"{cue.id}: on screen for {cue.duration:.2f}s, above the "
                f"{MAX_CUE_SECONDS}s maximum"
            )

    for earlier, later in zip(cues, cues[1:]):
        if later.start_seconds < earlier.end_seconds:
            problems.append(
                f"{earlier.id} overlaps {later.id} "
                f"({earlier.end_seconds:.3f}s > {later.start_seconds:.3f}s) — "
                "two glass panels would render on the same frame"
            )

    return problems


__all__ = [
    "MAX_CPS",
    "MIN_CUE_SECONDS",
    "MAX_CUE_SECONDS",
    "MAX_CUE_VISIBLE_CHARS",
    "TimedWord",
    "PersianCue",
    "build_cues",
    "audit_cues",
]
