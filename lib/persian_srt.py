"""Build a Persian subtitle sidecar (`.srt`) from word-level transcription output.

Sits between a transcriber and the compose stage. Its input is a flat list of timed
words; its output is an SRT file that ships *beside* the MP4.

## Why this is a sidecar and no longer burned into the frame

This module used to feed the composition's `cues` array, so every spoken phrase was
painted onto the video with a karaoke cursor tracking the voice. That was removed:
wall-to-wall painted transcript is the visual signature of automated short-form
captioning, and it left no empty frame for the footage or for the typographic
moments that now carry the on-screen text.

Removing it would have cost real accessibility, so the words did not disappear —
they moved. As an SRT they are selectable, translatable, searchable, and rendered by
the platform at the size the viewer chose, which is *better* for a viewer who needs
them than baked pixels at a size chosen here. What is lost is the viewer who watches
muted with no captions enabled, and that is the trade being made deliberately.

## The one decision this module makes

Where to end each cue. Everything else is bookkeeping. A cue that is too long
outruns the reader; one that is too short flickers; one that ends mid-clause reads as
an error even when the timing is perfect. Three limits shape the grouping, and the
reasoning for each is worth stating because they conflict:

* **Clause boundaries.** Persian punctuation («،» «؛» «.» «؟») marks a place the
  reader already expects to pause, so a cue ending there costs nothing. Splitting a
  clause in half costs a lot even when both halves fit every other limit.

* **Extent** (`MAX_CUE_SECONDS`, `MAX_CUE_VISIBLE_CHARS`). Past roughly six seconds a
  single cue loses the reader's thread. The character ceiling is now a *reading*
  limit rather than a layout one: nothing here knows how wide the player will draw
  the text, so 84 visible characters is the point past which a caption is a
  paragraph regardless of how it is drawn.

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

It does not decide line breaks, and it no longer emits per-word timings. Both existed
to serve a renderer that measured Estedad on a canvas and moved a karaoke cursor; an
SRT consumer does neither. Emitting them anyway would be dead data that a future
reader would assume something depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from lib.persian_text import (
    normalize,
    to_persian_digits,
    visible_length,
)

#: Reading-speed ceiling in visible characters per second.
#:
#: Unchanged at 21 even though the composition's own `MOMENT_READ_CPS` is 11, and the
#: difference is the point: a caption is read *while listening*, so it may run at
#: speaking pace, while a typographic moment is looked at and needs time for the
#: composition to register before reading starts. Two different jobs, two rates.
MAX_CPS = 21.0

#: Below this, a cue reads as a flash rather than as text.
MIN_CUE_SECONDS = 1.0

#: Past this, a single cue loses the reader's thread.
MAX_CUE_SECONDS = 6.0

#: Visible characters past which a caption is a paragraph. A long cue can satisfy
#: MAX_CPS by simply being long; this is the separate limit that stops it.
MAX_CUE_VISIBLE_CHARS = 84

#: Ranked clause terminators. A cue prefers to end on the strongest boundary
#: available inside its budget.
_STRONG_TERMINATORS = (".", "؟", "!", "…")
_WEAK_TERMINATORS = ("،", "؛", ":")
_TRAILING_CLOSERS = ("\"", "\x27", "»", "”", "’", ")", "]", "}", "）", "】", "〕", "〉", "》")

#: Gap between consecutive cues, seconds.
#:
#: Kept, and kept tiny, for a different reason than it originally had: an overlap no
#: longer stacks two panels in a frame, but SRT consumers disagree about what to do
#: with overlapping cues — some show both, some drop one — so non-overlapping output
#: is the only portable kind.
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
    """One subtitle cue, ready to be written into an SRT file."""

    id: str
    text: str
    start_seconds: float
    end_seconds: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    @property
    def cps(self) -> float:
        """Visible characters per second. The reading-speed metric."""
        if self.duration <= 0:
            return float("inf")
        return visible_length(self.text) / self.duration


def _boundary_text(word: str) -> str:
    """Normalize a word and ignore trailing closing quotes/brackets for punctuation."""
    stripped = normalize(word).rstrip()
    while stripped.endswith(_TRAILING_CLOSERS):
        stripped = stripped[:-1].rstrip()
    return stripped


def _terminator_rank(word: str) -> int:
    """3 for a strong clause end, 2 for a weak one, 0 otherwise."""
    stripped = _boundary_text(word)
    if stripped.endswith(_STRONG_TERMINATORS):
        return 3
    if stripped.endswith(_WEAK_TERMINATORS):
        return 2
    return 0


def _ends_with_hard_boundary(word: TimedWord) -> bool:
    """Whether automatic cue repair must preserve the boundary after this word."""
    return _terminator_rank(word.text) == 3


def _fits(
    words: list[TimedWord],
    extra: TimedWord,
    *,
    max_visible_chars: int = MAX_CUE_VISIBLE_CHARS,
    max_seconds: float = MAX_CUE_SECONDS,
) -> bool:
    """Whether `extra` can join `words` without breaking an actionable limit.

    Only the two limits that **grouping can actually influence** are checked here:
    total on-screen duration, and the character ceiling. Both bind on the group's own
    extent, so breaking earlier genuinely fixes them.

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

    if duration > max_seconds:
        return False
    if visible_length(text) > max_visible_chars:
        return False
    return True


def build_cues(
    words: Iterable[dict[str, Any]],
    *,
    persian_digits: bool = True,
    id_prefix: str = "cue",
    max_visible_chars: int = MAX_CUE_VISIBLE_CHARS,
    max_seconds: float = MAX_CUE_SECONDS,
) -> list[PersianCue]:
    """Group timed words into readable Persian cues.

    Args:
        words: Word entries as emitted by either transcriber — each needs
            `word`/`text`, `start`, and `end`. Both key spellings are accepted so
            the caller does not have to know which provider ran.
        persian_digits: Convert ASCII and Arabic-Indic digits to Persian-Indic.
            On by default: a Persian caption showing Western digits looks unfinished,
            and the conversion is safe because only digit glyphs are substituted.
        id_prefix: Prefix for generated cue IDs.
        max_visible_chars: Grouping ceiling. Burned captions may lower this while
            sidecar SRT keeps the repository default.
        max_seconds: Maximum cue extent; defaults to the SRT policy.

    Returns:
        Cues in timeline order. Never overlapping, never shorter than
        `MIN_CUE_SECONDS` unless the source audio itself is that short.

    Raises:
        ValueError: if a word entry lacks usable timing. Silently dropping it
            would shift every subsequent cue's timing by that word's duration,
            producing captions that drift out of sync with no visible cause.
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

    groups = _group_words(
        parsed, max_visible_chars=max_visible_chars, max_seconds=max_seconds
    )
    groups = _merge_short_groups(
        groups, max_visible_chars=max_visible_chars, max_seconds=max_seconds
    )
    groups = _rebalance_short_groups(
        groups, max_visible_chars=max_visible_chars, max_seconds=max_seconds
    )

    cues: list[PersianCue] = []
    for index, group in enumerate(groups):
        start = group[0].start
        end = group[-1].end
        if index + 1 < len(groups):
            end = min(end, groups[index + 1][0].start - CUE_GAP_SECONDS)
        end = max(end, start + 0.05)

        cues.append(
            PersianCue(
                id=f"{id_prefix}-{index + 1}",
                text=" ".join(w.text for w in group),
                start_seconds=start,
                end_seconds=end,
            )
        )

    return cues


def _group_words(
    words: list[TimedWord],
    *,
    max_visible_chars: int = MAX_CUE_VISIBLE_CHARS,
    max_seconds: float = MAX_CUE_SECONDS,
) -> list[list[TimedWord]]:
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
        if current and not _fits(
            current, word, max_visible_chars=max_visible_chars, max_seconds=max_seconds
        ):
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

        # A strong terminator is a semantic hard boundary. Preserve it even when
        # the resulting cue is short: a reported flash is less misleading than
        # joining a complete sentence/question to the next thought.
        if rank == 3:
            groups.append(current)
            current = []
            best_break = None
            best_rank = 0

    if current:
        groups.append(current)

    return groups


def _merge_short_groups(
    groups: list[list[TimedWord]],
    *,
    max_visible_chars: int = MAX_CUE_VISIBLE_CHARS,
    max_seconds: float = MAX_CUE_SECONDS,
) -> list[list[TimedWord]]:
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
            not _ends_with_hard_boundary(group[-1])
            and visible_length(text) <= max_visible_chars
            and combined_duration <= max_seconds
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
            combined_duration = combined[-1].end - combined[0].start
            if (
                not _ends_with_hard_boundary(merged[-2][-1])
                and visible_length(text) <= max_visible_chars
                and combined_duration <= max_seconds
            ):
                merged = merged[:-2] + [combined]

    return merged


def _rebalance_short_groups(
    groups: list[list[TimedWord]],
    *,
    max_visible_chars: int = MAX_CUE_VISIBLE_CHARS,
    max_seconds: float = MAX_CUE_SECONDS,
) -> list[list[TimedWord]]:
    """Repair a remaining short cue by moving the nearest boundary when possible.

    ``_merge_short_groups`` handles the common case where a whole short group can be
    folded into a neighbour.  A tighter burned-caption character ceiling can leave a
    different shape: both neighbours are already near the ceiling, but moving just one
    boundary word would make the short cue readable without making either neighbour
    invalid.  Keeping the flash merely because a *whole* merge does not fit is an
    avoidable grouping failure.

    Prefer borrowing the smallest suffix from the previous cue, then the smallest
    prefix from the next cue.  The donor must remain at least ``MIN_CUE_SECONDS`` and
    both resulting groups must stay inside the same character/duration budgets.  No
    timing or wording is invented; only the cue boundary moves.
    """
    if len(groups) <= 1:
        return groups

    result = [list(group) for group in groups]

    def duration(group: list[TimedWord]) -> float:
        return group[-1].end - group[0].start

    def fits(group: list[TimedWord]) -> bool:
        if not group:
            return False
        return (
            visible_length(" ".join(word.text for word in group)) <= max_visible_chars
            and duration(group) <= max_seconds
        )

    for index in range(len(result)):
        group = result[index]
        if duration(group) >= MIN_CUE_SECONDS:
            continue

        if index > 0:
            previous = result[index - 1]
            if _ends_with_hard_boundary(previous[-1]):
                previous = []
            for moved in range(1, len(previous)):
                donor = previous[:-moved]
                repaired = previous[-moved:] + group
                if (
                    duration(donor) >= MIN_CUE_SECONDS
                    and duration(repaired) >= MIN_CUE_SECONDS
                    and fits(donor)
                    and fits(repaired)
                ):
                    result[index - 1] = donor
                    result[index] = repaired
                    group = repaired
                    break

        if duration(group) >= MIN_CUE_SECONDS:
            continue

        if index + 1 < len(result) and not _ends_with_hard_boundary(group[-1]):
            following = result[index + 1]
            for moved in range(1, len(following)):
                repaired = group + following[:moved]
                donor = following[moved:]
                if (
                    duration(repaired) >= MIN_CUE_SECONDS
                    and duration(donor) >= MIN_CUE_SECONDS
                    and fits(repaired)
                    and fits(donor)
                ):
                    result[index] = repaired
                    result[index + 1] = donor
                    break

    return result


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
                f"{MAX_CUE_VISIBLE_CHARS} — the caption is a paragraph"
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
                f"({earlier.end_seconds:.3f}s > {later.start_seconds:.3f}s) — SRT "
                "consumers disagree about overlapping cues, so the file is not portable"
            )

    return problems


def _srt_timestamp(seconds: float) -> str:
    """Format one time as `HH:MM:SS,mmm`.

    Milliseconds are **truncated, not rounded**. Rounding up can push a cue's end
    past the next cue's start when they are separated by `CUE_GAP_SECONDS`, which is
    below one millisecond — reintroducing the overlap the gap exists to prevent, in
    the output file only, where `audit_cues` can no longer see it.
    """
    if seconds < 0:
        seconds = 0.0
    total_ms = int(seconds * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(cues: list[PersianCue]) -> str:
    """Render cues as SRT text.

    Two details are load-bearing for Persian and easy to get wrong:

    **No RLM or RTL override is inserted.** The temptation is to prefix each line
    with U+200F so players lay it out right-to-left. It is unnecessary — the Unicode
    bidi algorithm derives paragraph direction from the first strong character, which
    in Persian text is Persian — and it is harmful, because some players render the
    mark as a visible box and others include it in the text they hand to a translation
    service.

    **Cue numbering is 1-based and contiguous.** Several players stop parsing at the
    first non-sequential index rather than reporting an error, so a gap silently
    truncates the captions from that point on.

    Line terminators are CRLF, which the SRT convention uses and which every player
    accepts; LF-only files are mis-parsed by a few older ones.
    """
    blocks: list[str] = []
    for number, cue in enumerate(cues, start=1):
        start = _srt_timestamp(cue.start_seconds)
        end = _srt_timestamp(cue.end_seconds)
        blocks.append(f"{number}\r\n{start} --> {end}\r\n{cue.text}\r\n")
    return "\r\n".join(blocks)


__all__ = [
    "MAX_CPS",
    "MIN_CUE_SECONDS",
    "MAX_CUE_SECONDS",
    "MAX_CUE_VISIBLE_CHARS",
    "TimedWord",
    "PersianCue",
    "build_cues",
    "audit_cues",
    "render_srt",
]
