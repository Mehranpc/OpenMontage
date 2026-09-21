"""Validate and time the typographic moments of a Persian video.

A **moment** is one deliberate typographic event on screen for a few seconds with
empty frame before and after it. A 64-second video carries roughly eight. Between
them there is no text at all.

This module is the gate between an authored moment list and the renderer. It does
not author moments — choosing *which* figures and claims deserve the frame is an
editorial judgement made at the edit stage, with the script in hand — but it
refuses a list that cannot work, and it explains why in terms of the decision that
produced the fault.

## The shape a moment must have: one phrase, in order

A moment is **one grammatical Persian phrase with one emphasised span inside it**,
carried by an ordered `segments` list. The array order is the reading order, top to
bottom, exactly as the author wrote it:

    [{role: "lead",  text: "مطالعهٔ دانشگاه اولوی فنلاند روی"},
     {role: "hero",  text: "۲۲۶۴ نفر"}]

paints «مطالعهٔ دانشگاه اولوی فنلاند روی» and beneath it «۲۲۶۴ نفر». No sorting,
no role-priority table. Persian states the frame before the fact, and a layout
that rearranged the phrase to fit a template would break the sentence precisely
where the grammar matters most.

This replaced a slot model — `kicker` above, hero in the middle, `unit` beside it,
`label` below — whose every slot had its own size, colour, and alignment. What
reached the screen for the same study was a 260px numeral, «نفر» floating at its
baseline 550px to its left, and «دانشگاه اولو، فنلاند» on a third line: three
sizes, three left edges, and no sentence anywhere. Nothing said a *study* was being
described, because no slot was for saying it. The gates here exist so that shape
cannot come back: retired keys are rejected outright (see `RETIRED_MOMENT_KEYS`),
and each reveal step must carry exactly one hero.

## Additive builds, not replacements

A moment may reveal in steps (`revealAfterSeconds`). Later segments join the
phrase rather than replacing it, and earlier ones dim — the specific case being
two consecutive facts that belong to one thought, which previously arrived as two
separate moments the viewer experienced as text flashing by. A build is one
moment, so the inter-moment gap floor does not apply between its steps; the
reading model instead charges every step separately and refuses a build that
outruns its own timeline.

## The reading model

Time is charged per reveal step:

    fixation + Σ(chargeable chars)/READ_CPS + (blocks in the step − 1)·BLOCK_SECONDS

`fixation` is dead time the character count never saw: the entrance animation is
still settling for ~0.4s and the eye needs a beat to land. Charging only characters
is what let a 2.03s moment be declared adequate for 22 characters — arithmetically
fine, in practice unreadable, and exactly the «بیش از حد سریع رد میشن» complaint
measured. `MIN_SECONDS` is correspondingly higher than a caption's floor.

## Why a module exists for this instead of a JSON schema

Every rule here is relational. A schema can require that `startSeconds` is a
number; it cannot express that this moment must not begin until 0.9s after the
previous one ended, that the first moment must be on screen within 0.6s of the
start, that the whole set must not cover more than a bounded share of the runtime,
or that a step needs reading time in proportion to its own text. Those are the
rules that actually matter, because each of them is a way the output slides back
toward being a caption track.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Literal

from lib.persian_brand import validate_exact_text_record
from lib.persian_text import (
    break_class,
    compare_key,
    normalize,
    split_words,
    to_persian_digits,
    visible_length,
)
from lib.persian_text import BreakClass

MomentKind = Literal["figure", "term", "statement", "hook"]
SegmentRole = Literal["lead", "hero", "tail", "source"]

#: The four kinds. Mirrors `PersianMomentKind` in
#: `remotion-composer/src/persian/types.ts`; a contract test pins them together.
#: Editorial only — it no longer decides arrangement (segments do), it records what
#: the author judged the moment to be, which is what the audits reason about.
#: `hook` is declared, never inferred: the predecessor inferred hook-ness from the
#: flat display shape (a hero with `accentWords` and no non-`source` sibling), so
#: a claim+qualifier hook — a hero plus a tail, no `accentWords` — matched
#: nothing and silently lost every hook-scoped token. Declaring the kind is what
#: keeps that from recurring.
MOMENT_KINDS: frozenset[str] = frozenset({"figure", "term", "statement", "hook"})

#: The four roles. Mirrors `PersianSegmentRole`.
SEGMENT_ROLES: frozenset[str] = frozenset({"lead", "hero", "tail", "source"})

#: Reading rate for a moment, visible characters per second.
#:
#: Deliberately far below a subtitle's 21: a caption is read while listening, but a
#: moment is *looked at*, and the eye needs time to take in the composition before
#: it starts reading. Mirrors `MOMENT_READ_CPS` in `tokens.ts`.
READ_CPS = 11.0

#: Dead time before any reading happens, per reveal step, in seconds. The entrance
#: is still settling for ~0.43s and the eye then needs a beat to land. Mirrors
#: `MOMENT_FIXATION_SECONDS`.
FIXATION_SECONDS = 0.45

#: Cost of each additional block in the same reveal step, in seconds: a saccade
#: plus a refixation the character count does not see. Mirrors
#: `MOMENT_BLOCK_SECONDS`.
BLOCK_SECONDS = 0.3

#: Weight of a `source` segment's characters in the reading model. A citation set
#: in the smallest type is skimmed or skipped, but it is still ink on the screen.
#: Mirrors `MOMENT_SOURCE_READ_WEIGHT`.
SOURCE_READ_WEIGHT = 0.5

#: Floor on a moment's screen time. Below this it registers as a flash rather than
#: as a composed frame. Raised from the caption-era 1.8s along with the reading
#: model. Mirrors `MOMENT_MIN_SECONDS`.
MIN_SECONDS = 2.4

#: Ceiling on a moment's screen time. Not a readability limit — a long moment is
#: perfectly readable — but a pacing one. Raised from 6s because a built moment
#: legitimately holds longer: it is two or three reads, not one. Mirrors
#: `MOMENT_MAX_SECONDS`.
MAX_SECONDS = 9.0

#: Minimum empty frame between consecutive moments. Mirrors
#: `MOMENT_MIN_GAP_SECONDS`, and enforced on both sides of the boundary so the
#: renderer and the pipeline cannot disagree about whose job it was. A *build
#: step* inside one moment is not a new moment and is not subject to it.
MIN_GAP_SECONDS = 0.9

#: Numerical tolerance for authored decimal timeline boundaries. JSON decimal
#: times such as 43.04 - 42.14 can land infinitesimally below 0.9 in binary
#: floating-point and must not turn an exact policy boundary into a refusal.
TIMING_EPSILON_SECONDS = 1e-9

#: Latest the first moment may appear, in seconds. Mirrors
#: `OPENING_MOMENT_MAX_START_SECONDS`. Short-form feeds autoplay muted, so a video
#: that opens on silent footage has nothing on screen to hold a thumb — and the one
#: place "the narration will explain it" is false by construction. The deleted hook
#: *layer* was wrong because it was a second text layer, not because opening with
#: type was wrong; this rule gets the opening without the second layer.
OPENING_MAX_START_SECONDS = 0.6

#: Fraction of the runtime that may carry text.
#:
#: This is the rule that makes the output structurally different from a caption
#: track, and the only one that cannot be satisfied by a well-behaved caption track.
#: At 0.55 a 64-second video has at least 29 seconds of footage with nothing over it.
#:
#: The number is chosen from the reading model, not from taste: a moment that obeys
#: the model averages ~4s, so 8-9 moments per minute lands at 0.5-0.55 coverage
#: while 12-15 (the old band) cannot fit under the ceiling at honest durations at
#: all. That is not an accident — the coverage ceiling and the reading floor
#: *together* force the density they both want: fewer, richer, slower moments.
MAX_TEXT_COVERAGE = 0.55

#: Density sanity band, moments per minute. Lowered from 6-16 to 4.5-9 for the same
#: arithmetic the coverage ceiling encodes: the floor exists because a video with
#: two moments in a minute is not using the typographic layer (a planning failure,
#: not restraint), and the ceiling because many brief moments could satisfy the
#: coverage rule while still flickering.
MIN_MOMENTS_PER_MINUTE = 4.5
MAX_MOMENTS_PER_MINUTE = 9.0

#: Visible characters per segment, by role. These exist so the pipeline can reject
#: over-long text *before* a render, in a place where the browser's ladder search is
#: unavailable. They are empirically pinned, not re-derived from the ladder: with the
#: measured ≈0.44em per visible Persian character, a 30-char hero spans ~779px at
#: the 59px bottom rung (inside the ~881px vertical line budget) but ~911px at
#: 69px (past it), while a 42-char support line at the 32px lead floor spans
#: ~591px and a 40-char source at the 30px source floor ~528px — so the caps
#: admit the bottom rung while refusing anything that fits nowhere. A segment
#: past its ceiling cannot fit any rung.
MAX_HERO_CHARS = 30
MAX_SUPPORT_CHARS = 42
MAX_SOURCE_CHARS = 40

#: Ceiling on a flat-hook hero — a whole sentence at one size, not an emphasis
#: word. Sixty characters run to about four lines at the top rung, well inside
#: the height budget; the reading model and the coverage ceiling keep longer
#: hooks honest, so this number only refuses paragraphs masquerading as hooks.
MAX_FLAT_HERO_CHARS = 60

#: Cap on a segment's inline accent words (the flat-hook treatment).
#:
#: The policy is one or two keywords; the gate refuses past three. Three is the
#: boundary where "a keyword or two" has visibly become "several orange words",
#: and several orange words are no emphasis at all — the fault the one-hero rule
#: exists to prevent, restated in colour instead of size.
MAX_ACCENT_WORDS = 3

#: Semantic multi-word units the renderer must never split across rows.
#: The cap prevents layout metadata from becoming a second copy channel.
MAX_PHRASE_LOCKS = 8

CURATED_EDITORIAL_RECIPES: frozenset[str] = frozenset({
    "editorial-hero-balanced", "editorial-hero-compact", "editorial-callout-balanced",
})
_PRESENTATION_KEYS: frozenset[str] = frozenset({
    "treatment", "placement", "motion", "emphasis", "contrastMode", "contrastStrength", "recipeId", "sequenceMode",
})

#: Silhouette band a hook's lines must read inside, as a fraction.
#:
#: The silhouette ratio is the narrowest painted line width divided by the
#: widest, across every line of every non-`source` segment — lines, not
#: segments, so a wrapped tail counts. It is the single number that separates a
#: designed hook from a typeset one: the rejected flat arrangement measured 0.88
#: (two lines of nearly equal width read as a rectangle), while the reference
#: measures 0.62 and the approved c4 frame 0.647, and a hook squeezed to the
#: 0.55 lead ceiling measured 0.489 (a qualifier so narrow it reads as a caption
#: under a poster). The band passes the reference and c4 with margin on both
#: sides and refuses both the rectangle and the sliver; round numbers, so a
#: future re-measurement that moves a hundredth changes nothing. Mirrors
#: `HOOK_SILHOUETTE_MIN_RATIO` / `HOOK_SILHOUETTE_MAX_RATIO` in `tokens.ts`.
#: Enforced where real measured widths exist — the node-fit bridge in
#: `tools/video/persian_compose.py` — not here, because this module has no font.
#:
#: What this does to the flat style, stated plainly: the flat line breaker
#: minimises squared slack, which *balances* lines, so a flat hook measures
#: around 0.87–0.88 and fails this band. That is a true finding about the flat
#: style, not a calibration problem: a balanced block is a rectangle by
#: construction. The flat style would need a hook-specific break objective
#: before it could pass, and the band is not weakened to accommodate it.
HOOK_SILHOUETTE_MIN_RATIO = 0.52
HOOK_SILHOUETTE_MAX_RATIO = 0.78

#: Retired moment keys. Present in authored input → hard rejection, not a warning:
#: a slot that exists gets filled, and these slots produced three sizes on three
#: left edges with no sentence between them.
RETIRED_MOMENT_KEYS: tuple[str, ...] = (
    "text",
    "label",
    "kicker",
    "unit",
    "highlight",
    "highlightWords",
)


@dataclass
class PersianSegment:
    """One block of a moment's phrase."""

    role: SegmentRole
    text: str
    reveal_after_seconds: float = 0.0
    #: Inline accent words, matched by canonical form (`compare_key`).
    #:
    #: Empty everywhere except a flat-hook moment: there the whole segment paints
    #: at one size in primary ink and only these words carry the accent colour.
    #: Parsed from `accentWords` (a new segment-level key — unrelated to the
    #: retired moment-level `highlightWords`, which stays refused).
    accent_words: list[str] = field(default_factory=list)
    #: Multi-word semantic units that must remain on one rendered row. These are
    #: layout constraints, not painted copy; the segment text remains authoritative.
    phrase_locks: list[str] = field(default_factory=list)

    @property
    def visible_chars(self) -> int:
        return visible_length(self.text)


@dataclass
class PersianMoment:
    """One typographic moment, ready for the composition's `moments` array."""

    id: str
    kind: MomentKind
    start_seconds: float
    end_seconds: float
    segments: list[PersianSegment]
    purpose: str = ""
    user_authored_short_hook: bool = False
    presentation: dict[str, Any] = field(default_factory=dict)
    anchor_text: str = ""
    # Present only for copy that must survive artifact/props transport byte-for-byte.
    exact_text: dict[str, str] | None = None
    # Fitted total ink+gap height, px at nominal width. Set by the compose
    # step via canvas measurement when available, so the verifier can derive
    # the scrim plateau (``height/2 + margin`` around the optical centre) from
    # the same geometry the renderer used. Mirrors ``FittedMoment.heightPx``.
    stack_height_px: float | None = None
    stack_width_px: float | None = None
    # Resolved once by the browser fitter; renderer and collision planner consume it.
    layout_geometry: dict[str, float] | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    @property
    def visible_chars(self) -> int:
        """Total visible characters across every segment this moment paints."""
        return sum(segment.visible_chars for segment in self.segments)

    @property
    def chargeable_chars(self) -> float:
        """Characters charged to the reading model, source weighted."""
        return sum(
            segment.visible_chars
            * (SOURCE_READ_WEIGHT if segment.role == "source" else 1.0)
            for segment in self.segments
        )

    @property
    def hero(self) -> PersianSegment | None:
        heroes = [segment for segment in self.segments if segment.role == "hero"]
        return heroes[0] if heroes else None

    @property
    def has_build(self) -> bool:
        """True when any non-source segment reveals after the moment's own start."""
        return any(
            segment.role != "source" and segment.reveal_after_seconds > 0
            for segment in self.segments
        )

    @property
    def cps(self) -> float:
        """Chargeable characters per second of the moment's whole duration.

        Reported for diagnostics, not used as the gate: the gate is the per-step
        model in `min_read_seconds`, because a moment's average hides a final step
        that arrived a beat before the exit.
        """
        if self.duration <= 0:
            return float("inf")
        return self.chargeable_chars / self.duration

    def reveal_steps(self) -> list[list[PersianSegment]]:
        """Segments grouped by reveal time, source attached to the last step.

        Mirrors `momentRevealSteps` in `types.ts`. A step is everything that
        arrives together; a moment with no authored reveal is one step. The source
        segment is a citation on the whole moment rather than part of any step, so
        it is attached to the final step's reading window — it stays until the exit
        — while still never counting as a block.
        """
        by_time: dict[float, list[PersianSegment]] = {}
        source: list[PersianSegment] = []
        for segment in self.segments:
            if segment.role == "source":
                source.append(segment)
                continue
            by_time.setdefault(segment.reveal_after_seconds, []).append(segment)
        steps = [by_time[time] for time in sorted(by_time)]
        if source:
            if steps:
                steps[-1].extend(source)
            else:  # pragma: no cover - unreachable, a hero always exists
                steps = [list(source)]
        return steps

    @property
    def min_read_seconds(self) -> float:
        """Screen time this moment's own content requires, per the reading model.

        Every reveal step gets its own fixation and its own reading charge, and a
        step's reading window ends when the next step arrives (or, for the last,
        at the moment's exit). A build that outruns its own timeline therefore
        reports more time than the moment has, which `audit_moments` turns into a
        fault rather than a fast frame.
        """
        steps = self.reveal_steps()
        if not steps:  # pragma: no cover - a hero always exists
            return MIN_SECONDS

        def cost(step: list[PersianSegment]) -> float:
            blocks = sum(1 for segment in step if segment.role != "source")
            chars = sum(
                segment.visible_chars
                * (SOURCE_READ_WEIGHT if segment.role == "source" else 1.0)
                for segment in step
            )
            return FIXATION_SECONDS + chars / READ_CPS + max(0, blocks - 1) * BLOCK_SECONDS

        if len(steps) == 1:
            return max(MIN_SECONDS, cost(steps[0]))

        if self.presentation.get("sequenceMode") == "replace":
            # Replacement steps are mutually exclusive: earlier copy disappears
            # when the next alternative arrives, so reading charges do not stack
            # on top of authored reveal gaps. Per-step window sufficiency is audited
            # below against the actual reveal schedule.
            return max(MIN_SECONDS, sum(cost(step) for step in steps))

        # The first step holds until the second arrives; a middle step holds until
        # the next; the last holds until exit. Total required time is the sum of
        # each step's cost, plus the authored gaps between them.
        total = sum(cost(step) for step in steps)
        reveals = sorted(
            {
                segment.reveal_after_seconds
                for step in steps
                for segment in step
                if segment.role != "source"
            }
        )
        total += sum(reveals[i + 1] - reveals[i] for i in range(len(reveals) - 1))
        return max(MIN_SECONDS, total)

    def to_props(self) -> dict[str, Any]:
        """The JSON shape `PersianMoment` expects in the renderer.

        `endSeconds` is rounded **up** to the millisecond grid. Rounding half-even
        or down can land a serialized moment a fraction of a millisecond below its
        own `min_read_seconds` — `retime_moments` derives an exact end, this
        serialization carries it at 1ms granularity, and the pacing audit compares
        against the exact floor. The shipped failure was `needs 8.9455s but has
        8.945s`: a moment set that passed in memory and was refused on the JSON
        round-trip through `edit_decisions.json`. A reading floor must survive its
        own transport, so the end rounds up and the start rounds down, keeping the
        span at-or-above the floor in every serialized copy.
        """
        import math

        props: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "startSeconds": math.floor(self.start_seconds * 1000) / 1000,
            "endSeconds": math.ceil(self.end_seconds * 1000) / 1000,
            "segments": [
                {
                    "role": segment.role,
                    "text": segment.text,
                    **(
                        {"revealAfterSeconds": round(segment.reveal_after_seconds, 3)}
                        if segment.reveal_after_seconds > 0
                        else {}
                    ),
                    **(
                        {"accentWords": list(segment.accent_words)}
                        if segment.accent_words
                        else {}
                    ),
                    **(
                        {"phraseLocks": list(segment.phrase_locks)}
                        if segment.phrase_locks
                        else {}
                    ),
                }
                for segment in self.segments
            ],
        }
        if self.purpose:
            props["purpose"] = self.purpose
        if self.user_authored_short_hook:
            props["userAuthoredShortHook"] = True
        if self.presentation:
            props["presentation"] = dict(self.presentation)
        if self.anchor_text:
            props["anchorText"] = self.anchor_text
        if self.exact_text is not None:
            props["exactText"] = dict(self.exact_text)
        if self.stack_height_px is not None:
            props["stackHeightPx"] = round(float(self.stack_height_px), 2)
        if getattr(self, "stack_width_px", None) is not None:
            props["stackWidthPx"] = round(float(self.stack_width_px), 2)
        if self.layout_geometry is not None:
            props["layoutGeometry"] = dict(self.layout_geometry)
        return props


def _clean(value: Any, *, persian_digits: bool) -> str:
    """Normalize one authored string for painting.

    Normalization is applied here rather than trusted from the author because the
    renderer measures and paints exactly these bytes: an Arabic ك or ي that survives
    to the canvas measures at one width and paints at another in a font that has both,
    and the layout is then wrong by a few pixels for reasons invisible in the props.
    """
    if value is None:
        return ""
    text = normalize(str(value)).strip()
    if persian_digits and text:
        text = to_persian_digits(text)
    return text


def _clean_accent_words(
    value: Any, text: str, where: str, seg_index: int
) -> list[str]:
    """Normalize a segment's `accentWords` and check them against its own text.

    Each word must occur in the segment (compared by canonical form, so trailing
    punctuation never defeats the match), and there may be at most
    `MAX_ACCENT_WORDS` of them. Raised rather than filtered: a silently dropped
    accent word is an emphasis the author believes is on screen and is not.
    """
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(word, str) and word.strip() for word in value
    ):
        raise ValueError(
            f"{where} segment {seg_index} has accentWords={value!r}; expected a "
            "list of non-empty words."
        )
    words = [_clean(word, persian_digits=False) for word in value]
    if len(words) > MAX_ACCENT_WORDS:
        raise ValueError(
            f"{where} segment {seg_index} lists {len(words)} accent words; at "
            f"most {MAX_ACCENT_WORDS} are allowed. Several orange words are no "
            "emphasis at all — keep one or two keywords."
        )
    text_words = {
        compare_key(word) for word in split_words(text) if word != "\n"
    }
    for word in words:
        if compare_key(word) not in text_words:
            raise ValueError(
                f"{where} segment {seg_index} accents {word!r}, which is not in "
                f"its own text {text!r}. An accent word that never paints is an "
                "emphasis nobody sees."
            )
    return words


def _clean_phrase_locks(
    value: Any, text: str, where: str, seg_index: int
) -> list[str]:
    """Validate semantic multi-word units that layout may not split.

    Locks compare by canonical token form so punctuation and Arabic/Persian code
    point variants do not defeat matching, but the painted segment text is never
    rewritten. A lock must name a contiguous sequence of at least two words from
    its own segment; malformed metadata is refused rather than silently ignored.
    """
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(phrase, str) and phrase.strip() for phrase in value
    ):
        raise ValueError(
            f"{where} segment {seg_index} has phraseLocks={value!r}; expected a "
            "list of non-empty multi-word phrases."
        )
    if len(value) > MAX_PHRASE_LOCKS:
        raise ValueError(
            f"{where} segment {seg_index} lists {len(value)} phraseLocks; at most "
            f"{MAX_PHRASE_LOCKS} are allowed."
        )

    text_words: list[str | None] = [
        None if word == "\n" else compare_key(word) for word in split_words(text)
    ]
    result: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for raw_phrase in value:
        if "\n" in raw_phrase or "\r" in raw_phrase:
            raise ValueError(
                f"{where} segment {seg_index} phraseLocks entries must be single-line phrases."
            )
        phrase = _clean(raw_phrase, persian_digits=False)
        keys = tuple(
            compare_key(word) for word in split_words(phrase) if word != "\n"
        )
        if len(keys) < 2:
            raise ValueError(
                f"{where} segment {seg_index} phraseLocks entry {phrase!r} must contain at least two words."
            )
        if keys in seen:
            raise ValueError(
                f"{where} segment {seg_index} phraseLocks contains the same semantic phrase more than once."
            )
        found = any(
            all(
                text_words[start + offset] is not None
                and text_words[start + offset] == key
                for offset, key in enumerate(keys)
            )
            for start in range(0, len(text_words) - len(keys) + 1)
        )
        if not found:
            raise ValueError(
                f"{where} segment {seg_index} phraseLocks entry {phrase!r} is not a contiguous phrase in its own text {text!r}."
            )
        seen.add(keys)
        result.append(phrase)
    return result


def _coerce_reveal(value: Any, *, index: int, where: str) -> float:
    if value is None:
        return 0.0
    try:
        reveal = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{where} segment {index}: revealAfterSeconds {value!r} is not a number"
        ) from None
    if reveal < 0:
        raise ValueError(
            f"{where} segment {index}: revealAfterSeconds {reveal} is negative"
        )
    return reveal


def build_moments(
    authored: Iterable[dict[str, Any]],
    *,
    persian_digits: bool = True,
    id_prefix: str = "moment",
) -> list[PersianMoment]:
    """Normalize authored moments into timeline order.

    Args:
        authored: Moment dicts. Each needs `kind`, `segments` (a list of
            `{role, text, revealAfterSeconds?, phraseLocks?}` in reading order), and timing as
            either `startSeconds`/`endSeconds` or `start`/`end`.
        persian_digits: Convert ASCII and Arabic-Indic digits to Persian-Indic. On by
            default: Western digits in a Persian frame look unfinished, and the
            conversion touches only digit glyphs.
        id_prefix: Prefix for generated IDs, used when an entry has none.

    Returns:
        Moments sorted by start time. Sorting rather than preserving input order is
        deliberate — every downstream rule is about adjacency, and adjacency in an
        unsorted list is meaningless.

    Raises:
        ValueError: when an entry is malformed. Raised rather than skipped: a dropped
            moment leaves a silent hole where the edit expected text, and the
            render succeeds.
    """
    moments: list[PersianMoment] = []
    for index, raw in enumerate(authored):
        where = f"moment {index}"
        kind = str(raw.get("kind") or "").strip()
        if kind not in MOMENT_KINDS:
            raise ValueError(
                f"{where} has kind {kind!r}; expected one of {sorted(MOMENT_KINDS)}."
            )

        for key in RETIRED_MOMENT_KEYS:
            if key in raw:
                raise ValueError(
                    f"{where} carries the retired key {key!r}. Slot-per-role moments "
                    "(kicker above, hero, unit beside, label below) are gone — they "
                    "produced three type sizes on three different left edges with no "
                    "sentence anywhere. Express the phrase as ordered segments: "
                    "[{role:'lead', text:'مطالعهٔ دانشگاه اولوی فنلاند روی'}, "
                    "{role:'hero', text:'۲۲۶۴ نفر'}]."
                )

        raw_segments = raw.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            raise ValueError(
                f"{where} has no segments. A moment is one Persian phrase carried by "
                "an ordered segment list; the array order is the top-to-bottom "
                "reading order."
            )

        exact_text = (
            validate_exact_text_record(raw.get("exactText"))
            if raw.get("exactText") is not None
            else None
        )
        if (
            exact_text is not None
            and " ".join(exact_text["text"].split()) != exact_text["text"]
        ):
            raise ValueError(
                f"{where} strict copy must use one ASCII space between words and "
                "no leading, trailing, repeated, or line-break whitespace; "
                "unsupported whitespace is refused rather than repaired"
            )
        segments: list[PersianSegment] = []
        for seg_index, raw_segment in enumerate(raw_segments):
            if not isinstance(raw_segment, dict):
                raise ValueError(f"{where} segment {seg_index} is not an object")
            role = str(raw_segment.get("role") or "").strip()
            if role not in SEGMENT_ROLES:
                raise ValueError(
                    f"{where} segment {seg_index} has role {role!r}; expected one of "
                    f"{sorted(SEGMENT_ROLES)}."
                )
            if exact_text is None:
                text = _clean(
                    raw_segment.get("text"), persian_digits=persian_digits
                )
            else:
                authored_text = raw_segment.get("text")
                if not isinstance(authored_text, str) or authored_text == "":
                    raise ValueError(
                        f"{where} strict segment {seg_index} ({role}) needs a "
                        "non-empty string; strict copy is never coerced or stripped"
                    )
                text = authored_text
            if not text:
                raise ValueError(
                    f"{where} segment {seg_index} ({role}) has no text. An empty "
                    "segment reserves vertical space and paints nothing."
                )
            accent_words = _clean_accent_words(
                raw_segment.get("accentWords"), text, where, seg_index,
            )
            phrase_locks = _clean_phrase_locks(
                raw_segment.get("phraseLocks"), text, where, seg_index,
            )
            segments.append(
                PersianSegment(
                    role=role,  # type: ignore[arg-type]
                    text=text,
                    reveal_after_seconds=_coerce_reveal(
                        raw_segment.get("revealAfterSeconds"),
                        index=seg_index,
                        where=where,
                    ),
                    accent_words=accent_words,
                    phrase_locks=phrase_locks,
                )
            )

        if exact_text is not None:
            display_text = " ".join(
                segment.text for segment in segments if segment.role != "source"
            )
            if display_text != exact_text["text"]:
                raise ValueError(
                    f"{where} exactText.text does not equal the authored display "
                    "segments byte-for-byte; punctuation, code points, whitespace, "
                    "and digits may not be normalized"
                )

        start = raw.get("startSeconds", raw.get("start"))
        end = raw.get("endSeconds", raw.get("end"))
        if start is None or end is None:
            raise ValueError(
                f"{where} is missing timing; needs startSeconds/endSeconds or "
                "start/end"
            )

        raw_short = raw.get("userAuthoredShortHook", False)
        if not isinstance(raw_short, bool):
            raise ValueError(f"{where} userAuthoredShortHook must be true or false")
        raw_presentation = raw.get("presentation") or {}
        if not isinstance(raw_presentation, dict):
            raise ValueError(f"{where} presentation must be an object")
        unsupported_presentation = sorted(set(raw_presentation) - _PRESENTATION_KEYS)
        if unsupported_presentation:
            raise ValueError(f"{where} presentation contains unsupported freeform style keys: " + ", ".join(unsupported_presentation) + ". Use a curated recipe instead of agent-generated CSS.")
        recipe = raw_presentation.get("recipeId")
        if recipe is not None and recipe not in CURATED_EDITORIAL_RECIPES:
            raise ValueError(f"{where} presentation recipe {recipe!r} is unsupported; expected one of {sorted(CURATED_EDITORIAL_RECIPES)}")

        moments.append(
            PersianMoment(
                id=str(raw.get("id") or f"{id_prefix}-{index + 1}"),
                kind=kind,  # type: ignore[arg-type]
                start_seconds=float(start),
                end_seconds=float(end),
                segments=segments,
                purpose=_clean(raw.get("purpose"), persian_digits=False),
                user_authored_short_hook=raw_short,
                presentation=dict(raw_presentation),
                anchor_text=_clean(raw.get("anchorText"), persian_digits=False),
                exact_text=exact_text,
            )
        )

    moments.sort(key=lambda moment: moment.start_seconds)
    return moments


@dataclass
class MomentAudit:
    """The result of auditing a moment set."""

    problems: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    text_coverage: float = 0.0
    moments_per_minute: float = 0.0
    largest_gap_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "problems": list(self.problems),
            "advisories": list(self.advisories),
            "text_coverage": round(self.text_coverage, 4),
            "moments_per_minute": round(self.moments_per_minute, 2),
            "largest_gap_seconds": round(self.largest_gap_seconds, 2),
            "passed": self.passed,
        }


def _phrase_break_violations(moment: PersianMoment) -> list[str]:
    """Grammatical faults across segment boundaries — within a *reveal step* only.

    ## What is deliberately NOT checked, and why

    The in-block breaker forbids ending a line on a proclitic — «به», «و», «روی» —
    because inside one uniform block the reader relies on visual continuity to
    know the thought continues, and a line ending on a dangling preposition breaks
    that signal. But a *stack* boundary between a `lead` and a `hero` is not inside
    one uniform block: there is a size change, a colour change, and a designed gap,
    so the eye reads two deliberately separate blocks and the continuation is
    carried by the grammar, not by the typography.

    Enforcing the in-block rule at stack boundaries was tried and it rejects the
    canonical case: «مطالعهٔ دانشگاه اولوی فنلاند روی / ۲۲۶۴ نفر» — Persian
    states the frame before the fact, and that word order is exactly what the
    segment model exists to obey. A gate that blocks the canonical correct form is
    worse than no gate, so this audit does not apply line-break rules to role
    boundaries.

    ## What IS checked

    Two segments that arrive in the same reveal step and are set at the same size
    in the same colour — a `lead` and a `tail` — genuinely are one uniform block
    with a gap in it, so the in-block rules apply there.
    """
    violations: list[str] = []
    blocks = [segment for segment in moment.segments if segment.role != "source"]
    for earlier, later in zip(blocks, blocks[1:]):
        same_step = earlier.reveal_after_seconds == later.reveal_after_seconds
        same_class = {earlier.role, later.role} == {"lead", "tail"}
        if not (same_step and same_class):
            continue
        boundary = f"{earlier.role}→{later.role}"
        if not earlier.text.strip() or not later.text.strip():
            continue
        first_of_next = split_words(later.text)
        last_of_this = split_words(earlier.text)
        if not last_of_this or not first_of_next:
            continue
        klass = break_class(last_of_this[-1], first_of_next[0])
        if klass == BreakClass.FORBIDDEN:
            violations.append(
                f"{moment.id}: the {boundary} boundary breaks between "
                f"«{last_of_this[-1]}» and «{first_of_next[0]}» — two same-class "
                "segments in one step are one uniform block with a gap in it, so the "
                "in-block rules apply. Move the bound word across, or rephrase."
            )
    return violations


def is_claim_qualifier_hook(moment: PersianMoment) -> bool:
    """True when a moment has the claim+qualifier hook structure.

    A `hero` carrying the claim plus a `tail` completing it, no `accentWords`
    anywhere — the colour comes from the roles. Mirrors `isClaimQualifierHook`
    in `layout.ts`; the two are pinned together by the hook contract test, so a
    change to one that the other does not follow fails loudly rather than
    rendering a style nobody audited.
    """
    non_source = [
        segment for segment in moment.segments if segment.role != "source"
    ]
    if len(non_source) != 2:
        return False
    # Claim+qualifier is deliberately distinct from an ordinary lead+hero stack.
    # Only the authored hero-then-tail form receives hook-scoped sizing/tokens.
    valid_order = (non_source[0].role, non_source[1].role) == ("hero", "tail")
    return valid_order and not any(segment.accent_words for segment in moment.segments)




def is_context_claim_qualifier_hook(moment: PersianMoment) -> bool:
    """A 2.14-style pattern-interrupt hook with a small context line.

    The authored order is ``lead + hero + tail`` with no inline accents.  The
    purpose gate prevents ordinary historical hooks from silently changing style;
    compose additionally restricts this shape to Film Type 2.14+.
    """
    if moment.purpose != "hook-pattern-interrupt":
        return False
    non_source = [segment for segment in moment.segments if segment.role != "source"]
    if [segment.role for segment in non_source] != ["lead", "hero", "tail"]:
        return False
    return not any(segment.accent_words for segment in moment.segments)

def is_poster_stack_hook(moment: PersianMoment) -> bool:
    """True for a semantic poster stack used by retention-first opening hooks.

    The authored hook is partitioned into 2–5 simultaneous phrase blocks. Exactly
    one ``hero`` names the central subject/topic. Blocks before it are ``lead``
    setup/bridge phrases; blocks after it are ``tail`` connector/payoff phrases.
    The wording is unchanged — segmentation only gives the renderer semantic
    hierarchy. Inline ``accentWords`` are deliberately absent because the whole
    hero phrase owns the yellow emphasis.
    """
    if moment.kind != "hook" or moment.purpose != "hook-pattern-interrupt":
        return False
    non_source = [segment for segment in moment.segments if segment.role != "source"]
    if not 2 <= len(non_source) <= 5:
        return False
    if any(segment.accent_words for segment in non_source):
        return False
    hero_indexes = [index for index, segment in enumerate(non_source) if segment.role == "hero"]
    if len(hero_indexes) != 1:
        return False
    hero_index = hero_indexes[0]
    return (
        all(segment.role == "lead" for segment in non_source[:hero_index])
        and all(segment.role == "tail" for segment in non_source[hero_index + 1 :])
    )


def is_flat_display_hook(moment: PersianMoment) -> bool:
    """True when a moment has the flat display hook structure.

    A single `hero` carrying `accentWords` — the whole moment at one size with
    the emphasis in colour — and no sibling of any role but `source`. Mirrors
    `isFlatDisplayBlock` in `layout.ts`, kept working for a single-clause
    sentence where any split is arbitrary.
    """
    heroes = [segment for segment in moment.segments if segment.role == "hero"]
    if not heroes:
        return False
    if not all(segment.accent_words for segment in heroes):
        return False
    return all(
        segment.role in {"hero", "source"} for segment in moment.segments
    )


_ENUMERATION_SPLIT_RE = re.compile(r"\s*[،,؛;]\s*")


def _enumeration_parts(text: str) -> list[str]:
    parts = [part.strip() for part in _ENUMERATION_SPLIT_RE.split(str(text or "")) if part.strip()]
    return parts if len(parts) >= 2 else []


def _enumerated_anchor_integrity_violations(moment: PersianMoment) -> list[str]:
    """Keep list-style callouts lexically inside their spoken anchor items.

    Editorial shortening may drop whole words (``توجه دیداری`` -> ``توجه``), but
    it may not manufacture or morphologically truncate a replacement label
    (``درک فضایی`` -> ``فضا``). This narrow rule applies only when the narration
    anchor is an explicit comma/semicolon list and the display exposes the same
    number of list items, so ordinary paraphrase remains editorially available.
    """
    anchor_parts = _enumeration_parts(moment.anchor_text)
    if len(anchor_parts) < 2:
        return []
    visible = [segment.text for segment in moment.segments if segment.role != "source"]
    display_parts = _enumeration_parts(" ".join(visible))
    if len(display_parts) < 2 and len(visible) == len(anchor_parts):
        display_parts = [text.strip() for text in visible]
    if len(display_parts) != len(anchor_parts):
        return []

    problems: list[str] = []
    for index, (anchor_part, display_part) in enumerate(zip(anchor_parts, display_parts, strict=True), start=1):
        anchor_tokens = {
            compare_key(word) for word in split_words(anchor_part)
            if word != "\n" and compare_key(word)
        }
        display_tokens = [
            compare_key(word) for word in split_words(display_part)
            if word != "\n" and compare_key(word)
        ]
        foreign = [token for token in display_tokens if token not in anchor_tokens]
        if foreign:
            problems.append(
                f"{moment.id}: enumerated anchor item {index} is {anchor_part!r} but "
                f"display item {display_part!r} introduces token(s) {', '.join(foreign)!r}. "
                "List callouts may shorten by dropping whole anchored words, but may not "
                "invent or morphologically truncate a concept label."
            )
    return problems


def _audit_one(
    moment: PersianMoment, *, adaptive_pixel_typography: bool = False,
    simultaneous_hook_typography: bool = False,
) -> list[str]:
    """Faults internal to a single moment."""
    problems: list[str] = []

    if moment.duration <= 0:
        problems.append(
            f"{moment.id}: ends at {moment.end_seconds:.2f}s, at or before its "
            f"{moment.start_seconds:.2f}s start"
        )
        return problems

    heroes = [segment for segment in moment.segments if segment.role == "hero"]
    sources = [segment for segment in moment.segments if segment.role == "source"]

    sequence_mode = moment.presentation.get("sequenceMode") if moment.presentation else None
    if sequence_mode is not None and sequence_mode != "replace":
        problems.append(f"{moment.id}: unsupported sequenceMode {sequence_mode!r}.")
    if sequence_mode == "replace":
        if not adaptive_pixel_typography:
            problems.append(
                f"{moment.id}: replace sequence requires Film Type adaptive pixel typography; "
                "non-Film-Type renderers do not implement replacement paint semantics."
            )
        content = [segment for segment in moment.segments if segment.role != "source"]
        reveals = [segment.reveal_after_seconds for segment in content]
        if len(content) < 2:
            problems.append(f"{moment.id}: replace sequence requires at least two alternatives.")
        if sources:
            problems.append(f"{moment.id}: replace sequence does not accept a source row.")
        if any(segment.role != "hero" for segment in content):
            problems.append(f"{moment.id}: replace sequence alternatives must each be a hero segment.")
        if reveals and (reveals[0] != 0 or any(later <= earlier for earlier, later in zip(reveals, reveals[1:]))):
            problems.append(
                f"{moment.id}: replace sequence revealAfterSeconds values must start at 0 "
                "and be strictly increasing in authored order."
            )

    if len(heroes) == 0:
        problems.append(
            f"{moment.id}: no 'hero' segment. Nothing emphasised is a caption, not a "
            "moment — the whole phrase would paint at one size in one colour."
        )
    if len(sources) > 1:
        problems.append(f"{moment.id}: more than one 'source' segment; at most one.")
    if sources and moment.segments[-1].role != "source":
        problems.append(
            f"{moment.id}: a 'source' segment must be last — it is a citation "
            "appended to the phrase, not a part of it."
        )

    # One hero per reveal step. A built moment is two or three phrases arriving in
    # turn, each needing its own emphasis; what must never happen is two heroes
    # arriving together, because then neither is the emphasis.
    for step in moment.reveal_steps():
        step_heroes = [segment for segment in step if segment.role == "hero"]
        if len(step_heroes) != 1:
            problems.append(
                f"{moment.id}: the reveal step at +"
                f"{step_heroes[0].reveal_after_seconds if step_heroes else 0:.1f}s "
                f"carries {len(step_heroes)} 'hero' segments; exactly one is required."
            )

    # The flat-hook treatment: inline accent inside one block at one size. Only
    # on a hero (the accent span is still the emphasis), only as a single
    # non-source block (several blocks at several sizes are the sized hierarchy
    # the flat treatment exists to avoid), and only on the video's first moment
    # (every other moment keeps the sized lead/hero/tail model).
    accented = [segment for segment in moment.segments if segment.accent_words]
    for segment in accented:
        if segment.role != "hero":
            problems.append(
                f"{moment.id}: accentWords on a {segment.role} segment. Inline "
                "accent lives on the hero — the accent span is still the emphasis, "
                "expressed in colour rather than size."
            )
    non_source = [
        segment for segment in moment.segments if segment.role != "source"
    ]
    if accented and len(non_source) > 1:
        problems.append(
            f"{moment.id}: accentWords with {len(non_source)} content blocks. A "
            "flat moment is one block at one size; several blocks at several "
            "sizes are the sized hierarchy, which needs no inline accent."
        )
    if accented and moment.segments[-1].role == "source":
        problems.append(
            f"{moment.id}: accentWords with a source citation. A hook carries no "
            "citation — it is the opening frame, not the evidence."
        )

    # The hook's shape: declared `hook` must read as one of the two hook
    # styles — claim+qualifier (hero + tail, no inline accent) or flat display
    # (a single accent-carrying hero). Anything else wearing the hook's kind
    # gets the hook's tokens without the hook's design, which is how the
    # rejected rectangle happened: two lines at one size under no gate at all.
    if moment.kind == "hook" and not (
        is_claim_qualifier_hook(moment)
        or is_context_claim_qualifier_hook(moment)
        or is_poster_stack_hook(moment)
        or is_flat_display_hook(moment)
    ):
        roles = [segment.role for segment in moment.segments]
        problems.append(
            f"{moment.id}: kind is 'hook' but the segments "
            f"({'+'.join(roles)}) are neither claim+qualifier (hero + tail, no "
            "accentWords), context+claim+qualifier (lead + hero + tail for a "
            "hook-pattern-interrupt), nor flat display (a single hero carrying "
            "accentWords). A hook that matches no hook style silently loses "
            "every hook-scoped token — declare the style in the structure."
        )
    # Opening pattern-interrupts must remain clause-level copy. This gate is
    # purpose-scoped so historical/ordinary hooks keep their pinned behaviour.
    # A deliberately authored micro-hook is allowed only when the input says so
    # explicitly; automatic layout pressure may never collapse a hook to a noun.
    if moment.kind == "hook" and moment.purpose == "hook-pattern-interrupt":
        lexical = [
            word for segment in moment.segments if segment.role != "source"
            for word in split_words(segment.text) if word != "\n"
        ]
        if len(lexical) < 3 and not moment.user_authored_short_hook:
            problems.append(
                f"{moment.id}: hook-pattern-interrupt has only {len(lexical)} lexical "
                "token(s). Automatic one-word/fragment fallback is forbidden; keep a "
                "meaningful clause (normally at least 3 tokens), or change placement, "
                "crop/window, or shot. Set userAuthoredShortHook only when the user "
                "explicitly authored the short hook."
            )
        accented_tokens = sum(len(segment.accent_words) for segment in moment.segments)
        if len(lexical) <= 1 and accented_tokens and not moment.user_authored_short_hook:
            problems.append(
                f"{moment.id}: a one-token hook may not manufacture impact with "
                "accentWords/inline emphasis. Use clause-level copy or re-edit the "
                "shot/crop instead of underlining a fallback word."
            )

    if is_claim_qualifier_hook(moment) and any(
        segment.role == "source" for segment in moment.segments
    ):
        # The flat style's accentWords+source case is refused by its own rule
        # above; this covers the claim+qualifier style under the same reason.
        problems.append(
            f"{moment.id}: a hook carries no source citation — it is the "
            "opening frame, not the evidence."
        )

    for segment in moment.segments:
        chars = segment.visible_chars
        if adaptive_pixel_typography:
            continue
        if segment.role == "hero" and not segment.accent_words and chars > MAX_HERO_CHARS:
            problems.append(
                f"{moment.id}: hero is {chars} visible chars, above {MAX_HERO_CHARS}. "
                "The emphasis is not a paragraph — shorten it, or move the rest into "
                "a lead or tail."
            )
        if segment.role == "hero" and segment.accent_words and chars > MAX_FLAT_HERO_CHARS:
            problems.append(
                f"{moment.id}: flat hero is {chars} visible chars, above "
                f"{MAX_FLAT_HERO_CHARS}. A hook is a sentence, not a paragraph — "
                "shorten it."
            )
        if segment.role in {"lead", "tail"} and chars > MAX_SUPPORT_CHARS:
            problems.append(
                f"{moment.id}: {segment.role} is {chars} visible chars, above "
                f"{MAX_SUPPORT_CHARS} — a supporting line this long competes with the "
                "hero it supports."
            )
        if segment.role == "source" and chars > MAX_SOURCE_CHARS:
            problems.append(
                f"{moment.id}: source is {chars} visible chars, above "
                f"{MAX_SOURCE_CHARS}."
            )

    # A figure is a quantity; the phrase around it must say what the quantity counts.
    # The slot model could not enforce this (there was no sentence to check), which is
    # how a bare «۲۲۶۴» shipped over a university name with nothing connecting them.
    support = [
        segment for segment in moment.segments if segment.role in {"lead", "tail"}
    ]
    if moment.kind in {"figure", "term"} and not support:
        problems.append(
            f"{moment.id}: a {moment.kind} needs a lead or tail saying what it counts "
            "or names. A bare numeral or acronym reads as a design element rather "
            "than as information — the frame the user rejected as «معلوم نیست در "
            "مورد چیه»."
        )

    if moment.duration + TIMING_EPSILON_SECONDS < MIN_SECONDS:
        problems.append(
            f"{moment.id}: on screen for {moment.duration:.2f}s, below the "
            f"{MIN_SECONDS}s floor — reads as a flash rather than a composed frame"
        )
    if moment.duration - TIMING_EPSILON_SECONDS > MAX_SECONDS:
        problems.append(
            f"{moment.id}: on screen for {moment.duration:.2f}s, above the "
            f"{MAX_SECONDS}s ceiling — a static text frame this long reads as "
            "stalled, and the footage behind it is doing nothing"
        )

    # Film Type 2.16 opening hooks are one simultaneous 3–5 second composition.
    # Their complete copy is pixel-fitted and then judged from the rendered opening;
    # the legacy sequential-reading estimate must not veto a hook the browser can
    # actually present. Body callouts and older profiles retain the timing gate.
    if not (simultaneous_hook_typography and moment.kind == "hook"):
        required = moment.min_read_seconds
        if moment.duration + 1e-9 < required:
            problems.append(
                f"{moment.id}: needs {required:.2f}s for its own text (fixation + "
                f"reading + builds) but has {moment.duration:.2f}s. The reading model "
                "charges the entrance the character count never saw — that dead time is "
                "the «بیش از حد سریع رد میشن» complaint, measured."
            )

    if sequence_mode == "replace" and len(moment.reveal_steps()) >= 2:
        content_steps = moment.reveal_steps()
        reveal_times = sorted({
            segment.reveal_after_seconds
            for segment in moment.segments if segment.role != "source"
        })
        for index, (step, reveal_at) in enumerate(zip(content_steps, reveal_times, strict=True)):
            next_at = reveal_times[index + 1] if index + 1 < len(reveal_times) else moment.duration
            available = next_at - reveal_at
            chars = sum(segment.visible_chars for segment in step if segment.role != "source")
            blocks = sum(1 for segment in step if segment.role != "source")
            needed = FIXATION_SECONDS + chars / READ_CPS + max(0, blocks - 1) * BLOCK_SECONDS
            if available + TIMING_EPSILON_SECONDS < needed:
                problems.append(
                    f"{moment.id}: replace sequence step at +{reveal_at:.2f}s needs "
                    f"{needed:.2f}s but has {available:.2f}s before the next alternative."
                )

    for segment in moment.segments:
        if segment.reveal_after_seconds >= moment.duration:
            problems.append(
                f"{moment.id}: segment ({segment.role}) reveals at "
                f"+{segment.reveal_after_seconds:.2f}s but the moment is only "
                f"{moment.duration:.2f}s long, so it would never appear."
            )

    problems.extend(_phrase_break_violations(moment))
    problems.extend(_enumerated_anchor_integrity_violations(moment))
    return problems


def audit_moments(
    moments: list[PersianMoment], *, duration_seconds: float, v2: bool = False,
    adaptive_pixel_typography: bool = False,
    simultaneous_hook_typography: bool = False,
) -> MomentAudit:
    """Audit a moment set against every rule that can be checked without rendering.

    `problems` are faults: the set should not be rendered. `advisories` are
    observations a reviewer should see but which do not block, because the honest
    remedy is an editorial judgement rather than a mechanical fix.

    The split matters. Making everything a problem trains the next agent to route
    around the audit; making everything advisory means nothing is enforced. What
    belongs in `problems` is what has exactly one correct resolution.
    """
    audit = MomentAudit()

    if duration_seconds <= 0:
        audit.problems.append(
            f"duration_seconds is {duration_seconds}; coverage and density cannot be "
            "computed without the video's own length"
        )
        return audit

    for moment in moments:
        audit.problems.extend(_audit_one(
            moment, adaptive_pixel_typography=adaptive_pixel_typography,
            simultaneous_hook_typography=simultaneous_hook_typography,
        ))

    ordered = sorted(moments, key=lambda moment: moment.start_seconds)

    # The flat hook is the opening frame's treatment, not a second text model.
    # One video, one hook: any moment past the first carrying inline accent is a
    # second flat moment, which reads as indecision about what the model is.
    if not v2:
        for later in ordered[1:]:
            if any(segment.accent_words for segment in later.segments):
                audit.problems.append(
                    f"{later.id}: accentWords past the first moment. The flat-hook "
                    "treatment belongs to moment-1 alone; every other moment keeps "
                    "the sized lead/hero/tail model."
                )

    # The hook kind is the opening moment's declaration, not a second text
    # model either: a hook past the first moment is a second opening, which
    # reads the same indecision from the other side.
    for later in ordered[1:]:
        if later.kind == "hook":
            audit.problems.append(
                f"{later.id}: kind 'hook' past the first moment. The hook is "
                "the opening frame — declare what the later moment is "
                "(figure, term, or statement) instead."
            )

    # Adjacency. Enforced here as well as in the renderer, deliberately: the renderer
    # catches it at render time, which is minutes and a full clip stage too late.
    for earlier, later in zip(ordered, ordered[1:]):
        gap = later.start_seconds - earlier.end_seconds
        if gap < 0:
            audit.problems.append(
                f"{earlier.id} overlaps {later.id} by {-gap:.2f}s. Two moments paint "
                "two right-anchored stacks on the same rows, which is unreadable."
            )
        elif gap + TIMING_EPSILON_SECONDS < MIN_GAP_SECONDS:
            audit.problems.append(
                f"{earlier.id} → {later.id}: only {gap:.2f}s of empty frame between "
                f"them, below the {MIN_GAP_SECONDS}s floor. Without that gap the "
                "moments read as a caption track, which is the specific outcome this "
                "model exists to prevent."
            )

    if ordered:
        if ordered[0].start_seconds > OPENING_MAX_START_SECONDS:
            audit.problems.append(
                f"{ordered[0].id} starts at {ordered[0].start_seconds:.2f}s; the "
                f"first moment must be on screen within {OPENING_MAX_START_SECONDS}s "
                "of the start. Feeds autoplay muted, so a video that opens on silent "
                "footage has nothing on screen to hold a thumb — the one place where "
                "«the narration will explain it» is false by construction."
            )
        last = ordered[-1]
        if last.end_seconds > duration_seconds + 0.05:
            audit.problems.append(
                f"{last.id} ends at {last.end_seconds:.2f}s, past the video's "
                f"{duration_seconds:.2f}s duration — it would be cut mid-moment"
            )

    covered = sum(moment.duration for moment in ordered)
    audit.text_coverage = covered / duration_seconds
    audit.moments_per_minute = len(ordered) / (duration_seconds / 60.0)

    gaps = [0.0] if not ordered else [ordered[0].start_seconds]
    gaps.extend(
        later.start_seconds - earlier.end_seconds
        for earlier, later in zip(ordered, ordered[1:])
    )
    gaps.append(duration_seconds - ordered[-1].end_seconds if ordered else duration_seconds)
    audit.largest_gap_seconds = max(gaps)

    if audit.text_coverage > MAX_TEXT_COVERAGE:
        audit.problems.append(
            f"text covers {audit.text_coverage:.0%} of the runtime, above the "
            f"{MAX_TEXT_COVERAGE:.0%} ceiling. This is the rule that separates a "
            "typographic edit from a caption track: the footage needs frames with "
            "nothing over them. Cut the weakest moments rather than shortening every "
            "moment, which would break the reading-time floor instead."
        )

    if len(ordered) >= 2 and audit.moments_per_minute > MAX_MOMENTS_PER_MINUTE:
        audit.problems.append(
            f"{audit.moments_per_minute:.1f} moments per minute, above "
            f"{MAX_MOMENTS_PER_MINUTE}. Many brief moments satisfy the coverage "
            "ceiling while still reading as a flickering caption track."
        )

    if ordered and audit.moments_per_minute < MIN_MOMENTS_PER_MINUTE:
        audit.advisories.append(
            f"{audit.moments_per_minute:.1f} moments per minute, below the "
            f"{MIN_MOMENTS_PER_MINUTE} the pipeline expects. Advisory rather than a "
            "fault: restraint is legitimate, but confirm the script's figures and key "
            "terms are actually getting the frame."
        )

    if not ordered:
        audit.advisories.append(
            "no moments at all — the video will carry footage, narration, and the "
            "watermark, and nothing else. Legitimate for a purely visual piece; a "
            "planning failure for anything with a claim in it."
        )

    kinds = {moment.kind for moment in ordered}
    if len(ordered) >= 4 and kinds == {"statement"}:
        audit.advisories.append(
            "every moment is a statement. Figures and terms in the script are being "
            "set as running text, which is the arrangement they read worst in — a "
            "quantity wants to be a figure and an acronym wants to be a term."
        )

    builds = [moment for moment in ordered if moment.has_build]
    if len(ordered) >= 6 and not builds:
        audit.advisories.append(
            "no moment builds. Two consecutive facts that belong to one thought read "
            "best as one additive moment (revealAfterSeconds), where the earlier line "
            "stays and dims rather than being replaced — worth considering for at "
            "least one pairing in the set."
        )

    return audit


__all__ = [
    "MOMENT_KINDS",
    "SEGMENT_ROLES",
    "READ_CPS",
    "FIXATION_SECONDS",
    "BLOCK_SECONDS",
    "SOURCE_READ_WEIGHT",
    "MIN_SECONDS",
    "MAX_SECONDS",
    "MIN_GAP_SECONDS",
    "OPENING_MAX_START_SECONDS",
    "MAX_TEXT_COVERAGE",
    "MIN_MOMENTS_PER_MINUTE",
    "MAX_MOMENTS_PER_MINUTE",
    "MAX_HERO_CHARS",
    "MAX_SUPPORT_CHARS",
    "MAX_SOURCE_CHARS",
    "MAX_FLAT_HERO_CHARS",
    "MAX_ACCENT_WORDS",
    "HOOK_SILHOUETTE_MIN_RATIO",
    "HOOK_SILHOUETTE_MAX_RATIO",
    "RETIRED_MOMENT_KEYS",
    "PersianSegment",
    "PersianMoment",
    "MomentAudit",
    "build_moments",
    "audit_moments",
    "is_claim_qualifier_hook",
    "is_poster_stack_hook",
    "is_flat_display_hook",
]
