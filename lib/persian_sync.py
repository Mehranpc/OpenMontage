"""Bind moments to the narration, by deriving their timings from the voice.

## The failure this exists to prevent

The predecessor of this module did not exist, and the shipped render is what that
cost. Its moments had been authored for a *previous* narration of the same script
(66.08s) and then rescaled by the duration ratio onto the new voiceover (63.86s):
`old × (63.86/66.08)`, every start and end, to within half a millisecond. The
arithmetic is flawless and the result is unsynchronized — the scale factor preserves
the *shape* of the old edit and nothing about the new speech, because the words do
not move linearly. Measured against the voice, the lead-varied from +3.41s early to
−1.07s late, and the video read as «حس سینک بودن صدا با نمایش رو نمیده», which was
reported as a mystery because nothing in the pipeline recorded where the timings
had come from.

Two structural faults allowed it:

1. **Moments carried no anchor.** A timing is a number; nothing distinguished a
   moment timed against this narration from one timed against another file, so a
   rescale passed every gate on its way to the render.
2. **Nothing re-derived timings from the transcript.** The word timings — the
   ground truth of when each phrase is spoken — sat in the asset manifest the whole
   time, unused.

## What this module does

`anchor_moments` re-derives each moment's start from the narration words it names:
find the anchor phrase in the word timings, back the start off by a lead-in so the
type arrives just before the words do, and extend past the last anchor word by a
hold so the type does not vanish mid-phrase. `audit_sync` then compares the authored
timings against the derived ones — a moment that cannot be located in the narration
is a fault, and a moment whose authored start disagrees with the derived one by
more than `MAX_START_DRIFT_SECONDS` is a fault too. A rescaled timing set fails the
second check by construction, and a moment anchored to a different video's voice
fails the first.

## Matching an anchor phrase to words

Transcription words come back normalized in isolation — «هورمون‌ها» as spoken is
often «هورمون ها» as transcribed, and a Persian ezafe is never transcribed — so
matching is done on `compare_key` with a sliding window over the word sequence:
find the window whose joined key maximizes overlap with the anchor's key. Not
string equality, which fails on exactly the common words an anchor is made of.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

from lib.persian_moments import PersianMoment
from lib.persian_text import compare_key, normalize, split_words, visible_length

#: How many seconds before the anchor's first word the moment should start.
#:
#: The type must be arriving when the words land, not after them — a viewer hears
#: the phrase and sees the frame for it in the same beat, which is the felt sense
#: of «سینک». 0.25 is short enough that the moment never feels early and long
#: enough to cover the entrance (13 frames ≈ 0.43s at 30fps) mostly arriving as
#: the words begin.
ANCHOR_LEAD_IN_SECONDS = 0.25

#: How many seconds past the anchor's last word the moment should stay.
#:
#: Not zero, because a moment that exits exactly as the phrase ends reads as
#: snatched away. Not larger, because the hold eats into the inter-moment gap and
#: into the coverage ceiling.
ANCHOR_HOLD_SECONDS = 0.35

#: How far an authored start may drift from the derived one before it is a fault.
#:
#: Not zero, because authoring legitimately nudges a moment — a beat earlier for
#: tension, a beat later to clear a word boundary. 0.5 is the threshold at which a
#: viewer stops experiencing the text and the voice as one event, which is the
#: thing being protected. The rescaled set this module was written against had
#: drifts of 3.41s.
MAX_START_DRIFT_SECONDS = 0.5

#: Film Type 2.16 opening hooks are complete simultaneous compositions rather than
#: sequential reading windows. Retiming binds their start to narration while the
#: product contract owns the display duration.
SIMULTANEOUS_HOOK_MIN_SECONDS = 3.0
SIMULTANEOUS_HOOK_MAX_SECONDS = 5.0

#: Shortest anchor phrase, in visible characters. An anchor of one or two letters
#: matches words all over the transcript and the derived position is noise.
MIN_ANCHOR_CHARS = 3


@dataclass
class TimedWord:
    """One narration word with its measured span. Mirrors the transcriber output."""

    word: str
    start: float
    end: float

    @classmethod
    def from_dicts(cls, rows: Iterable[dict[str, Any]]) -> list["TimedWord"]:
        words: list["TimedWord"] = []
        for row in rows:
            word = str(row.get("word") or "").strip()
            if not word:
                continue
            start = float(row.get("start"))
            end = float(row.get("end"))
            if end <= start:
                continue
            words.append(cls(word=word, start=start, end=end))
        words.sort(key=lambda timed: timed.start)
        return words


def _sync_compare_key(word: str) -> str:
    """Comparison key for narration anchors with narrow ASR spelling folds.

    Some Persian ASR providers emit the older yeh-with-hamza spelling in words
    such as «فضائی» where approved copy uses «فضایی».  Treat only the «ئی»/«یی»
    sequence as equivalent here so timing alignment can consume the full spoken
    anchor without broadening the repository-wide lexical normalization contract.
    """
    return compare_key(word).replace("ئی", "یی")


def _key_of(words: Sequence[str]) -> str:
    """A comparable key for a word run: normalized, punctuation-free, joined."""
    return " ".join(
        _sync_compare_key(word) for word in words if _sync_compare_key(word)
    )


def find_anchor_span(
    words: Sequence[TimedWord], anchor_text: str
) -> tuple[int, int] | None:
    """Locate `anchor_text` in the word sequence, as `[first_index, last_index]`.

    A sliding window: every run of consecutive words up to `len(anchor_words) + 2`
    long is keyed and compared. Longest key-prefix match wins, so the span covers
    as much of the anchor as the transcript actually contains, and a missed trailing
    word (the ezafe that is never transcribed) does not lose the match.
    """
    anchor_words = [word for word in split_words(anchor_text) if compare_key(word)]
    if not anchor_words:
        return None
    anchor_key = _key_of(anchor_words)
    if visible_length(anchor_key) < MIN_ANCHOR_CHARS:
        return None

    best: tuple[int, int, int] | None = None  # (matched_length, start, end)
    max_window = min(len(words), len(anchor_words) + 2)
    for start in range(len(words)):
        for window in range(1, max_window + 1):
            end = start + window
            if end > len(words):
                break
            candidate_key = _key_of([timed.word for timed in words[start:end]])
            if not candidate_key:
                continue
            common = _common_prefix_length(anchor_key, candidate_key)
            if common < MIN_ANCHOR_CHARS:
                continue
            if best is None or common > best[0]:
                best = (common, start, end - 1)
            if candidate_key == anchor_key:
                return start, end - 1

    if best is None:
        return None
    return best[1], best[2]


def _enumeration_parts(text: str) -> list[str]:
    """Return explicit comma/semicolon list items, or an empty list for prose."""
    normalized = str(text or "")
    for separator in (",", "؛", ";"):
        normalized = normalized.replace(separator, "،")
    parts = [part.strip() for part in normalized.split("،") if part.strip()]
    return parts if len(parts) >= 2 else []


def _enumerated_display_anchor_problems(moment: PersianMoment) -> list[str]:
    """Bind list-style editorial callouts to the spoken list they summarize.

    A list callout that anchors to unrelated earlier prose can be perfectly timed
    numerically while still appearing seconds before the words it displays.  The
    same comparison also preserves spoken list order while allowing whole-word
    shortening inside each item (for example ``توجه دیداری`` -> ``توجه``).

    The opening ``hook-pattern-interrupt`` is a deliberate semantic replacement:
    its ``anchorText`` supplies the narration clock while hook authority separately
    binds the viewer-visible result-first copy.  A prose comma inside that hook is
    therefore not evidence of a spoken enumeration and must not be checked against
    the opening narration as though it were a body list callout.
    """
    if moment.kind == "hook" and moment.purpose == "hook-pattern-interrupt":
        return []
    list_segments = [
        parts
        for segment in moment.segments
        if segment.role == "hero"
        for parts in [_enumeration_parts(segment.text)]
        if parts
    ]
    if not list_segments:
        return []
    display_parts = list_segments[0]
    anchor_parts = _enumeration_parts(moment.anchor_text)
    if len(anchor_parts) != len(display_parts):
        return [
            f"{moment.id}: enumerated display must bind to an anchor containing "
            f"the same spoken list; display has {len(display_parts)} item(s) but "
            f"anchor «{moment.anchor_text}» has {len(anchor_parts)}."
        ]

    problems: list[str] = []
    for index, (anchor_part, display_part) in enumerate(
        zip(anchor_parts, display_parts, strict=True), start=1
    ):
        anchor_tokens = {
            compare_key(word)
            for word in split_words(anchor_part)
            if compare_key(word)
        }
        display_tokens = [
            compare_key(word)
            for word in split_words(display_part)
            if compare_key(word)
        ]
        foreign = [token for token in display_tokens if token not in anchor_tokens]
        if foreign:
            problems.append(
                f"{moment.id}: enumerated display item {index} «{display_part}» "
                f"does not preserve spoken order from anchor item «{anchor_part}». "
                "List callouts may drop whole anchored words but may not reorder "
                "or substitute concepts."
            )
    return problems


def _common_prefix_length(a: str, b: str) -> int:
    """Characters of shared prefix between two keys, counting only non-space runs.

    A partial *word* is not a partial match — «هورمون» matching «هورمون‌ها» counts
    only when the whole word agrees, so the length is snapped down to the last
    space that both keys share, plus the whole-word characters after it.
    """
    limit = min(len(a), len(b))
    index = 0
    while index < limit and a[index] == b[index]:
        index += 1
    if index >= limit:
        return index
    # Snap down to the last full word: a shared prefix of a word is not a shared word.
    snapped = a.rfind(" ", 0, index)
    return snapped + 1 if snapped != -1 else 0


@dataclass
class AnchorBinding:
    """One moment's derived timing from the narration."""

    moment_id: str
    anchor_text: str
    matched_words: list[str]
    #: Derived from the narration, or None when the anchor could not be located.
    derived_start: float | None
    derived_end: float | None
    #: The authored values, for the drift comparison.
    authored_start: float
    authored_end: float

    @property
    def located(self) -> bool:
        return self.derived_start is not None


def anchor_moments(
    moments: Sequence[PersianMoment], words: Sequence[TimedWord]
) -> list[AnchorBinding]:
    """Derive each moment's timing from the narration words it names.

    Every moment must carry an `anchor_text` naming the words it belongs to — that
    is the field that makes a rescaled timing set fail, because a rescale moves the
    numbers away from where the named words actually are. The start is the anchor's
    first word minus `ANCHOR_LEAD_IN_SECONDS`, floored at 0; the end is the anchor's
    last word plus `ANCHOR_HOLD_SECONDS`. Reading time may extend the end — the
    phrase must be readable, not merely coextensive with its own speech — so the
    binding's `derived_end` also respects `min_read_seconds`.
    """
    bindings: list[AnchorBinding] = []
    for moment in moments:
        anchor = moment.anchor_text or (moment.hero.text if moment.hero else "")
        span = find_anchor_span(words, anchor) if anchor else None
        if span is None:
            bindings.append(
                AnchorBinding(
                    moment_id=moment.id,
                    anchor_text=anchor,
                    matched_words=[],
                    derived_start=None,
                    derived_end=None,
                    authored_start=moment.start_seconds,
                    authored_end=moment.end_seconds,
                )
            )
            continue

        first, last = span
        start = max(0.0, words[first].start - ANCHOR_LEAD_IN_SECONDS)
        speech_end = words[last].end + ANCHOR_HOLD_SECONDS
        # The moment must remain readable for its own content even if the speaker
        # moves on: reading time extends past the speech, never shortens it.
        end = max(speech_end, start + moment.min_read_seconds)
        bindings.append(
            AnchorBinding(
                moment_id=moment.id,
                anchor_text=anchor,
                matched_words=[timed.word for timed in words[first : last + 1]],
                derived_start=start,
                derived_end=end,
                authored_start=moment.start_seconds,
                authored_end=moment.end_seconds,
            )
        )
    return bindings


@dataclass
class SyncAudit:
    """The result of auditing authored timings against the narration."""

    problems: list[str]
    bindings: list[AnchorBinding]

    @property
    def passed(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "problems": list(self.problems),
            "passed": self.passed,
            "bindings": [
                {
                    "momentId": binding.moment_id,
                    "anchor": binding.anchor_text,
                    "matched": binding.matched_words,
                    "derivedStart": (
                        round(binding.derived_start, 3)
                        if binding.derived_start is not None
                        else None
                    ),
                    "derivedEnd": (
                        round(binding.derived_end, 3)
                        if binding.derived_end is not None
                        else None
                    ),
                    "authoredStart": round(binding.authored_start, 3),
                    "authoredEnd": round(binding.authored_end, 3),
                }
                for binding in self.bindings
            ],
        }


def audit_sync(
    moments: Sequence[PersianMoment], words: Sequence[TimedWord]
) -> SyncAudit:
    """Compare authored timings against the narration-derived ones.

    Refuses on three conditions, in increasing severity:

    1. A moment with no anchor at all (advisory-level if the set is empty of words;
       the pipeline runs silent projects too, and there the sync audit is vacuous).
    2. A moment whose anchor cannot be located in the narration — either the anchor
       text is wrong for this voiceover, or the timings were authored for another
       file entirely. The rescaled set fails here or below.
    3. A located moment whose authored start drifts more than
       `MAX_START_DRIFT_SECONDS` from the derived one.
    """
    problems: list[str] = []
    if not words:
        return SyncAudit(problems=problems, bindings=[])

    bindings = anchor_moments(moments, words)

    for moment, binding in zip(moments, bindings):
        problems.extend(_enumerated_display_anchor_problems(moment))
        if not binding.anchor_text:
            problems.append(
                f"{moment.id}: no anchorText and no hero to derive one from. A "
                "moment that does not name the words it belongs to cannot be "
                "checked against the narration, which is how a rescaled timing "
                "set passed every gate before this module existed."
            )
            continue
        if not binding.located:
            problems.append(
                f"{moment.id}: anchor «{binding.anchor_text}» was not found in the "
                "narration word timings. Either the anchor text does not match "
                "this voiceover, or the moment timings were authored against a "
                "different narration and rescaled onto this one — the exact fault "
                "that produced up to 3.4s of drift in the shipped render."
            )
            continue
        assert binding.derived_start is not None
        drift = abs(binding.authored_start - binding.derived_start)
        if drift > MAX_START_DRIFT_SECONDS:
            problems.append(
                f"{moment.id}: starts at {binding.authored_start:.2f}s but its "
                f"anchor words are spoken at {binding.derived_start:.2f}s — a drift "
                f"of {drift:.2f}s, above the {MAX_START_DRIFT_SECONDS}s a viewer "
                "forgives. Re-derive the timing with `anchor_moments` rather than "
                "scaling it: a duration ratio preserves the shape of the old edit "
                "and nothing about where this voice actually speaks."
            )

    return SyncAudit(problems=problems, bindings=bindings)


def retime_moments(
    moments: Sequence[PersianMoment], words: Sequence[TimedWord], *,
    simultaneous_hook_typography: bool = False,
) -> list[PersianMoment]:
    """Return a *new* moment list with timings re-derived from the narration.

    The edit stage's remedy when `audit_sync` refuses: rather than nudging numbers
    by hand, re-bind every moment to its anchor and take the derived timing. The
    caller still owns the inter-moment rules — run `audit_moments` on the result,
    which will catch any moment the voice pushed into its neighbour.
    """
    bindings = anchor_moments(moments, words)
    retimed: list[PersianMoment] = []
    for moment, binding in zip(moments, bindings):
        if not binding.located:
            retimed.append(moment)
            continue
        assert binding.derived_start is not None and binding.derived_end is not None
        derived_end = binding.derived_end
        if simultaneous_hook_typography and moment.kind == "hook":
            product_duration = min(
                SIMULTANEOUS_HOOK_MAX_SECONDS,
                max(SIMULTANEOUS_HOOK_MIN_SECONDS, moment.duration),
            )
            derived_end = binding.derived_start + product_duration
        retimed.append(
            replace(
                moment,
                start_seconds=binding.derived_start,
                end_seconds=derived_end,
            )
        )
    return retimed


__all__ = [
    "ANCHOR_LEAD_IN_SECONDS",
    "ANCHOR_HOLD_SECONDS",
    "MAX_START_DRIFT_SECONDS",
    "SIMULTANEOUS_HOOK_MIN_SECONDS",
    "SIMULTANEOUS_HOOK_MAX_SECONDS",
    "MIN_ANCHOR_CHARS",
    "TimedWord",
    "AnchorBinding",
    "SyncAudit",
    "find_anchor_span",
    "anchor_moments",
    "audit_sync",
    "retime_moments",
    "retime_moments_from_dicts",
]


def retime_moments_from_dicts(
    moments: Sequence[PersianMoment], word_dicts: Iterable[dict[str, Any]], *,
    simultaneous_hook_typography: bool = False,
) -> list[PersianMoment]:
    """`retime_moments` for callers holding raw transcriber rows."""
    return retime_moments(
        moments, TimedWord.from_dicts(word_dicts),
        simultaneous_hook_typography=simultaneous_hook_typography,
    )
