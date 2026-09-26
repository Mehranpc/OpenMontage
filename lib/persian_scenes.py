"""Scene-plan gates for the Persian footage pipeline.

The footage rules that this pipeline's whole repair turned on — the subject anchor quota,
co-presence over substitution, the banned stock-medical vocabulary, the adjacent-variety
rule — existed only as prose in `scene-director.md` and as `review_focus` lines in the
manifest. Prose is what the first run had, and the first run produced a video about a
medical check-up: twelve queries, each a defensible translation of its own beat, and
together a different video from the one the brief described.

So the rules are here, where a stage can run them before its checkpoint. The evidence that
this was the missing layer rather than a nice addition: the *repaired* plan, written by hand
against the rewritten skill, still contained `close up hands coffee cup medication pills
table` on beat-10. The rule was read, the beat felt like an exception, and the query went in
anyway. A check does not have that option.

These functions return problems and advisories; they do not repair. A plan that fails them
represents a decision to revisit — change the query, or make the beat typographic — not
something to smooth over.
"""

from __future__ import annotations

import json
import math

from lib.persian_moments import MIN_MOMENTS_PER_MINUTE
from typing import Any

#: Stock-library shorthand for "health", forbidden unless the script names the thing.
#:
#: Every entry was in the coffee run's query list, and the run's footage was a waist
#: measurement, a bicep, a bathroom scale, test tubes, a glucose monitor, a DNA render and
#: a blood-pressure cuff. They are also generic enough that the same clips appear in every
#: health video on the internet, so a viewer has seen them and knows they mean nothing.
#:
#: Matched as substrings against the lowercased query, which is deliberately blunt: a
#: check that can be evaded by word order is a check that will be. `pill` rather than
#: `pills capsules` because the prose form was a phrase nobody types.
BANNED_QUERY_TERMS = (
    "doctor",
    "patient",
    "blood test",
    "dna",
    "laboratory",
    "test tube",
    "microscope",
    "hospital",
    "medical chart",
    "stethoscope",
    "pill",
    "capsule",
    "measuring waist",
    "measuring tape",
    "weighing scale",
    "weight scale",
    "bathroom scale",
    "blood pressure cuff",
    "syringe",
    "nurse",
    "clinic",
)

#: Fraction of footage beats that must show the subject literally.
#:
#: 40% rather than a majority because the remaining beats have real work — the mechanism,
#: the study, the consequence. It is a floor on recognisability, not a ceiling on variety.
MIN_SUBJECT_FRACTION = 0.4

# The parts of a frame a copy-bearing event may declare as staying clear. Deliberately
# coarse: this is the intent the search steers by, not a geometry engine -- the measured
# placement check remains authoritative and unchanged.
#
# Each region is a normalized rect, because a region can be clear and still be unusable:
# Film Type vertical reserves the bottom 35% for captions, so `lower_band` names space
# where editorial type cannot go at all. That was declared on a real run and cost a
# placement cycle to discover (#164).
#: (x, y, width, height), normalized. The convention matters and was previously
#: inconsistent with the reader, which silently clamped `right_column` past the frame.
_NEGATIVE_SPACE_RECTS: dict[str, tuple[float, float, float, float]] = {
    "left_column": (0.0, 0.0, 0.33, 1.0),
    "right_column": (0.67, 0.0, 0.33, 1.0),
    "upper_band": (0.0, 0.0, 1.0, 0.33),
    "lower_band": (0.0, 0.67, 1.0, 0.33),
    "centre_band": (0.2, 0.33, 0.6, 0.34),
    "full_frame": (0.0, 0.0, 1.0, 1.0),
}

NEGATIVE_SPACE_REGIONS = frozenset(_NEGATIVE_SPACE_RECTS)

# A region must overlap the profile's editorial safe area by at least this much of the
# frame before it can be asked to hold type.
_MIN_SERVICEABLE_REGION_AREA = 0.02

#: A region must also be WIDE enough to hold a laid-out column. The profile's narrowest
#: curated recipe column is `columnFractions` 0.56 of the safe width, so a column region
#: 0.33 of the frame wide can never host type at all -- declaring one guarantees a
#: placement refusal three phases later. Width is the profile-derived bound; the height a
#: given phrase needs is content-dependent and stays the renderer's business.
_MIN_RECIPE_COLUMN_FRACTION = 0.56

#: Queries per beat. Two, because the third was always a paraphrase of the second — the
#: first run wrote three per beat and downloaded 36 clips to use 12.
QUERIES_PER_BEAT = 2

#: Ordered fallback ladder from the production spec. Typography is the terminal
#: beat-level escape hatch and therefore is not a valid footage-event level.
FALLBACK_LEVELS = (
    "exact_literal",
    "emotional_human",
    "adjacent_metaphor",
    "abstract",
)

REWARD_OPENING_DIRECTIONS = frozenset({
    "parent_to_child_reward", "child_resistance", "parent_child_conflict", "child_distress",
})


def audit_opening_semantic_shots(shots: list[dict[str, Any]]) -> list[str]:
    """Validate explicit opening-hook evidence carried to the final shot boundary.

    The contract activates only when a shot explicitly declares narrativeRole=hook;
    historical edits without that new visual-event metadata remain reproducible.
    """
    opening = sorted(
        (shot for shot in shots if shot.get("narrativeRole") == "hook"
         and float(shot.get("startSeconds", 0.0)) < 3.0),
        key=lambda shot: float(shot.get("startSeconds", 0.0)),
    )
    if not opening:
        return []
    shot = opening[0]
    label = str(shot.get("visualEventId") or shot.get("id") or "opening shot")
    problems: list[str] = []
    role = str(shot.get("semanticRole") or "").strip()
    direction = str(shot.get("semanticDirection") or "").strip()
    if not role:
        problems.append(f"{label}: opening hook requires semanticRole")
    if not direction:
        problems.append(f"{label}: opening hook requires semanticDirection")
    if shot.get("openingSemanticMatch") is not True:
        problems.append(f"{label}: openingSemanticMatch must be true after reviewing the selected window")
    if not str(shot.get("selectionReason") or "").strip():
        problems.append(f"{label}: opening hook requires selectionReason describing what is visibly in frame")
    if not isinstance(shot.get("showsSubject"), bool):
        problems.append(f"{label}: showsSubject must be true or false")
    if not isinstance(shot.get("humanPresence"), bool):
        problems.append(f"{label}: humanPresence must be true or false")
    if role == "reward_problem_hook":
        if direction not in REWARD_OPENING_DIRECTIONS:
            problems.append(
                f"{label}: reward_problem_hook semanticDirection must be one of "
                + ", ".join(sorted(REWARD_OPENING_DIRECTIONS))
            )
        if shot.get("showsSubject") is not True:
            problems.append(f"{label}: reward_problem_hook must visibly show the subject")
        if shot.get("humanPresence") is not True:
            problems.append(f"{label}: reward_problem_hook requires visible human presence")
    return problems

#: Affects where a human read usually carries more meaning than an object-only stock shot.
#: The gate surfaces absence as an advisory rather than pretending every emotional idea
#: can only be shown with a face.
EMOTIONAL_AFFECTS = frozenset({
    "fear", "conflict", "embarrassment", "distraction", "stress", "relief",
})


def _beats(scene_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The beat list, from wherever this plan keeps it.

    Both shapes are in use: the artifact nests the planning block under `metadata`, while
    the block itself — the shape the skill documents and an agent assembles first — has
    `beats` at the top level. Accepting both means a caller cannot silently pass a plan
    whose beats are invisible to the gate, which would report a clean audit of nothing.
    """
    beats = scene_plan.get("beats")
    if beats is None:
        beats = (scene_plan.get("metadata") or {}).get("beats", [])
    return list(beats or [])


def _subject(scene_plan: dict[str, Any]) -> str | None:
    """The visual subject, from either shape, for the same reason as `_beats`."""
    subject = scene_plan.get("subject")
    if not subject:
        subject = (scene_plan.get("metadata") or {}).get("subject")
    return str(subject) if subject else None


def _footage_beats(beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [beat for beat in beats if not beat.get("typographic")]


def _footage_units(
    beats: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Expand semantic beats into the visual events the viewer actually sees.

    Older plans used one footage beat as both the semantic unit and the shot unit.
    New plans may declare ``visual_events`` inside a beat.  Once that list exists,
    its entries own shot-level search/affect fields and the semantic beat no longer
    has to collapse to one clip.  Legacy plans remain readable as one implicit event
    per footage beat so existing checkpoints can still be audited.
    """
    units: list[dict[str, Any]] = []
    problems: list[str] = []
    seen_ids: set[str] = set()
    has_explicit_events = False

    for beat in beats:
        if beat.get("typographic"):
            if beat.get("visual_events"):
                problems.append(
                    f'{beat.get("id")}: typographic beats cannot also declare visual_events'
                )
            continue

        raw_events = beat.get("visual_events")
        if raw_events is None:
            unit = dict(beat)
            unit["semantic_beat_id"] = str(beat.get("id") or "")
            unit["visual_event_id"] = None
            units.append(unit)
            continue

        has_explicit_events = True
        if not isinstance(raw_events, list) or not raw_events:
            problems.append(
                f'{beat.get("id")}: visual_events must be a non-empty list for a footage beat'
            )
            continue

        total_duration = 0.0
        for index, raw_event in enumerate(raw_events):
            if not isinstance(raw_event, dict):
                problems.append(
                    f'{beat.get("id")}: visual_event[{index}] must be an object'
                )
                continue
            event = dict(raw_event)
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                problems.append(f'{beat.get("id")}: visual_event[{index}] has no id')
            elif event_id in seen_ids:
                problems.append(f'duplicate visual_event id {event_id!r}')
            else:
                seen_ids.add(event_id)

            try:
                duration = float(event.get("duration_seconds") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration <= 0:
                problems.append(
                    f'{event_id or beat.get("id")}: visual event duration_seconds must be > 0'
                )
            total_duration += max(0.0, duration)

            if not str(event.get("desired_affect") or "").strip():
                problems.append(
                    f'{event_id or beat.get("id")}: explicit visual events require desired_affect'
                )

            for field in (
                "narration_span", "intent", "subject", "action", "motif",
                "visual_search_brief", "shot_composition", "conflict_visibility",
            ):
                if not str(event.get(field) or "").strip():
                    problems.append(
                        f'{event_id or beat.get("id")}: explicit visual events require {field}'
                    )

            if not isinstance(event.get("human_presence"), bool):
                problems.append(
                    f'{event_id or beat.get("id")}: human_presence must be true or false'
                )

            if str(event.get("narrative_role") or "").strip() == "hook":
                semantic_role = str(event.get("semantic_role") or "").strip()
                semantic_direction = str(event.get("semantic_direction") or "").strip()
                if not semantic_role:
                    problems.append(f'{event_id or beat.get("id")}: opening hook requires semantic_role')
                if not semantic_direction:
                    problems.append(f'{event_id or beat.get("id")}: opening hook requires semantic_direction')
                if semantic_role == "reward_problem_hook":
                    if semantic_direction not in REWARD_OPENING_DIRECTIONS:
                        problems.append(
                            f'{event_id or beat.get("id")}: reward_problem_hook semantic_direction must be one of '
                            + ", ".join(sorted(REWARD_OPENING_DIRECTIONS))
                        )
                    if event.get("shows_subject") is not True:
                        problems.append(f'{event_id or beat.get("id")}: reward_problem_hook must show_subject')
                    if event.get("human_presence") is not True:
                        problems.append(f'{event_id or beat.get("id")}: reward_problem_hook requires human_presence')

            fallback_level = str(event.get("fallback_level") or "").strip()
            if fallback_level not in FALLBACK_LEVELS:
                problems.append(
                    f'{event_id or beat.get("id")}: fallback_level must be one of '
                    + ", ".join(FALLBACK_LEVELS)
                )

            importance = event.get("importance")
            if isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 3:
                problems.append(
                    f'{event_id or beat.get("id")}: importance must be integer 1, 2, or 3'
                )

            event["semantic_beat_id"] = str(beat.get("id") or "")
            event["visual_event_id"] = event_id or None
            units.append(event)

        try:
            beat_duration = float(beat.get("duration_seconds") or 0.0)
        except (TypeError, ValueError):
            beat_duration = 0.0
        if beat_duration > 0 and abs(total_duration - beat_duration) > 0.05:
            problems.append(
                f'{beat.get("id")}: visual_events total {total_duration:.2f}s does not match '
                f'semantic beat duration {beat_duration:.2f}s'
            )

    return units, problems, has_explicit_events


def _editorial_safe_area(fmt: str) -> tuple[float, float, float, float] | None:
    """The profile's editorial safe area as (x, y, w, h), or None when unavailable."""
    try:
        from lib.paths import REPO_ROOT

        profile = json.loads(
            (REPO_ROOT / "styles" / "persian-footage" / "film-type.json").read_text(
                encoding="utf-8"
            )
        )
        formats = profile["formats"]
        raw = formats[fmt if fmt in formats else "vertical"]["safeArea"]
    except (OSError, KeyError, ValueError, TypeError, ImportError):
        return None
    left = float(raw.get("left", raw.get("side", 0.0)))
    right = float(raw.get("right", raw.get("side", 0.0)))
    top = float(raw.get("top", 0.0))
    bottom = float(raw.get("bottom", 0.0))
    return (left, top, max(0.0, 1.0 - left - right), max(0.0, 1.0 - top - bottom))


def _region_serviceable_span(region: tuple[float, float, float, float],
                            safe: tuple[float, float, float, float]) -> tuple[float, float]:
    """How much of a declared region the editorial safe area can actually host type in."""
    rx, ry, rw, rh = region
    sx, sy, sw, sh = safe
    width = max(0.0, min(rx + rw, sx + sw) - max(rx, sx))
    height = max(0.0, min(ry + rh, sy + sh) - max(ry, sy))
    return width, height


def audit_scene_plan(
    scene_plan: dict[str, Any],
    *,
    subject: str | None = None,
    script_text: str = "",
    typographic_budget: int | None = None,
) -> dict[str, Any]:
    """Measure a scene plan against the footage rules. Empty `problems` means clean.

    Args:
        scene_plan: The scene_plan artifact.
        subject: The video's visual subject. Defaults to `metadata.subject`; a plan with
            neither is itself a problem, since every other rule is stated against it.
        script_text: The full narration. A banned term is allowed when the script names
            it — «آزمایش خون» earns `blood test` — so the exemption needs the script to
            check against. Persian, so the check is on the *concept* the agent declares
            via `names_banned_term`, not on a translation this module would have to
            invent.
        typographic_budget: From `brief.metadata.typographic_beat_budget`.

    Returns:
        `problems` (must be fixed), `advisories` (judgements deliberately not enforced),
        and the measured numbers: `subject_fraction`, `footage_beats`, `queries_total`.
    """
    problems: list[str] = []
    advisories: list[str] = []

    beats = _beats(scene_plan)
    if not beats:
        return {
            "problems": ["the scene plan has no beats — nothing to audit"],
            "advisories": [],
            "subject_fraction": 0.0,
            "footage_beats": 0,
            "visual_events": 0,
            "uses_visual_events": False,
            "queries_total": 0,
            "sourcing_order": [],
        }

    subject = subject or _subject(scene_plan)
    if not subject:
        problems.append(
            "no subject recorded. Every footage rule is stated against the subject, so a "
            "plan without one cannot be audited — and a plan written without one is how "
            "twelve defensible queries become a video about something else."
        )

    footage_beats = _footage_beats(beats)
    footage, visual_event_problems, has_explicit_events = _footage_units(beats)
    problems.extend(visual_event_problems)
    queries_total = sum(len(unit.get("queries") or []) for unit in footage)

    # Importance changes retry order, not the global download ceiling. High-value
    # events consume the bounded alternate-query pass first; ordinary events do not
    # get starved by an unbounded search escalation. Legacy implicit events default to 1.
    def importance_rank(unit: dict[str, Any]) -> int:
        value = unit.get("importance")
        return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 3 else 1

    sourcing_order = [
        str(unit.get("visual_event_id") or unit.get("id") or "")
        for unit in sorted(footage, key=importance_rank, reverse=True)
    ]

    for unit in footage:
        if not unit.get("visual_event_id"):
            continue
        affect = str(unit.get("desired_affect") or "").strip().lower()
        if affect in EMOTIONAL_AFFECTS and not unit.get("human_presence"):
            advisories.append(
                f'{unit.get("id")}: desired_affect {affect!r} usually benefits from '
                "human presence. Confirm an object-only choice is intentional rather "
                "than generic stock avoidance failing silently."
            )
        if importance_rank(unit) == 3 and unit.get("fallback_level") == "abstract":
            advisories.append(
                f'{unit.get("id")}: importance 3 has fallen to abstract footage. '
                "Re-check literal, emotional-human, and adjacent-metaphor candidates "
                "before accepting the weakest footage fallback."
            )

    # --- Anchor quota -----------------------------------------------------------------
    if footage:
        if not footage[0].get("shows_subject"):
            problems.append(
                f'{footage[0].get("id")}: the first footage beat/event must show the subject. '
                "It is the frame that sets what the video is about, and a video opening "
                "on a laboratory is a video about medicine whatever the narration says."
            )
        if not footage[-1].get("shows_subject"):
            problems.append(
                f'{footage[-1].get("id")}: the last footage beat/event must show the subject. '
                "It is the frame the viewer remembers."
            )

        showing = sum(1 for beat in footage if beat.get("shows_subject"))
        fraction = showing / len(footage)
        if fraction < MIN_SUBJECT_FRACTION:
            problems.append(
                f"only {showing} of {len(footage)} footage units show the subject "
                f"({fraction:.0%}), against {MIN_SUBJECT_FRACTION:.0%} required. The "
                "remaining beats have real work to do, so this is a floor on "
                "recognisability rather than a ceiling on variety."
            )
    else:
        fraction = 0.0
        problems.append("no footage beats — every beat is marked typographic")

    # --- Negative space for copy-bearing events ---------------------------------------
    # A moment can only be placed where the frame is empty. Left undeclared, the search
    # is free to pick footage whose subject fills (or crosses) the frame, and the
    # collision is discovered at preflight -- one moment per repair cycle. Naming the
    # clear region at planning time is what lets the search prefer footage that leaves
    # room (#164).
    for beat in beats:
        for event in beat.get("visual_events") or []:
            if not isinstance(event, dict) or not event.get("carries_moment"):
                continue
            declared = str(event.get("negative_space") or "").strip()
            label = f'{beat.get("id")}/{event.get("id")}'
            if not declared:
                problems.append(
                    f"{label}: carries a typographic moment but declares no "
                    "`negative_space`, so nothing constrains the search to footage the "
                    "moment can actually sit on. Declare which part of the frame stays "
                    f"clear: one of {sorted(NEGATIVE_SPACE_REGIONS)}."
                )
            elif declared not in NEGATIVE_SPACE_REGIONS:
                problems.append(
                    f"{label}: `negative_space` {declared!r} is not one of "
                    f"{sorted(NEGATIVE_SPACE_REGIONS)}; the placement check cannot use it."
                )
            else:
                safe = _editorial_safe_area(str(scene_plan.get("format") or "vertical"))
                if safe is not None:
                    usable_w, usable_h = _region_serviceable_span(
                        _NEGATIVE_SPACE_RECTS[declared], safe
                    )
                    if usable_w * usable_h < _MIN_SERVICEABLE_REGION_AREA:
                        problems.append(
                            f"{label}: `negative_space` {declared!r} lies outside the "
                            "profile's editorial safe area, so type cannot be placed there "
                            "at all -- a region can be clear and still be unusable. The "
                            "profile reserves that part of the frame; declare a region with "
                            "safe-area room instead."
                        )
                    elif usable_w < _MIN_RECIPE_COLUMN_FRACTION * safe[2]:
                        problems.append(
                            f"{label}: `negative_space` {declared!r} is only "
                            f"{usable_w:.2f} of the frame wide inside the safe area, but the "
                            "profile's narrowest curated column is "
                            f"{_MIN_RECIPE_COLUMN_FRACTION} of the safe width "
                            f"({_MIN_RECIPE_COLUMN_FRACTION * safe[2]:.2f}). Type cannot be "
                            "laid out there at all, so declaring it guarantees a placement "
                            "refusal later. Use a band or the full frame instead."
                        )

    # --- Enough moments to be the product ---------------------------------------------
    # Declaring fewer copy-bearing events is the cheapest way to satisfy every placement
    # gate, and nothing else names the cost: `audit_moments` treats its moments-per-minute
    # floor as an advisory, so a plan carrying one moment passes the edit stage and ships a
    # video with almost no typography. Run 6 did exactly that -- one moment, no refusals.
    # The film is *defined* by its moments, so this is a problem, not an advisory.
    duration = 0.0
    for beat in beats:
        try:
            duration += float(beat.get("duration_seconds") or 0.0)
        except (TypeError, ValueError):
            continue
    if duration > 0:
        carrying = sum(
            1
            for beat in beats
            for event in (beat.get("visual_events") or [])
            if isinstance(event, dict) and event.get("carries_moment")
        )
        target = (scene_plan.get("metadata") or {}).get("moment_target")
        try:
            required = int(target) if target is not None else 0
        except (TypeError, ValueError):
            required = 0
        # Only when the plan states a target. This is a consistency check between the
        # plan's own declared intent and what it declares it can carry, not a new global
        # floor -- a plan that names no target is not making a claim to contradict.
        if required > 0 and carrying < required:
            problems.append(
                f"only {carrying} event(s) carry a typographic moment, against "
                f"{required} for a {duration:.1f}s film. Declaring fewer moments makes "
                "every placement gate easier to satisfy, which is exactly why it cannot be "
                "left to the author's judgement: the moments are the product, and a plan "
                "that carries one ships a video with almost no typography."
            )

    # --- Banned vocabulary ------------------------------------------------------------
    for beat in footage:
        exempt = bool(beat.get("names_banned_term"))
        for query in beat.get("queries") or []:
            lowered = str(query).lower()
            for term in BANNED_QUERY_TERMS:
                if term not in lowered:
                    continue
                if exempt:
                    advisories.append(
                        f'{beat.get("id")}: query {query!r} uses {term!r}, allowed '
                        "because the beat declares the script names it. Confirm the "
                        "subject is in the same frame — the exemption permits "
                        "co-presence, not substitution."
                    )
                    continue
                problems.append(
                    f'{beat.get("id")}: query {query!r} uses banned stock-medical '
                    f"vocabulary {term!r}. This is what a query returns when it was "
                    "written about the topic rather than about the shot. If the script "
                    "genuinely names it, set names_banned_term: true on the beat and "
                    "pair it with the subject in one frame."
                )

    # --- Substitution ------------------------------------------------------------------
    # A beat that does not show the subject and whose queries never mention it is a
    # substitution. Advisory rather than a problem: some beats legitimately leave the
    # subject (a gym, a desk), and the quota already bounds how many.
    if subject:
        needle = str(subject).lower()
        for beat in footage:
            if beat.get("shows_subject"):
                continue
            queries = [str(query).lower() for query in beat.get("queries") or []]
            if queries and not any(needle in query for query in queries):
                advisories.append(
                    f'{beat.get("id")}: no query mentions {subject!r} and the beat does '
                    "not show it. Co-presence — the subject beside the other thing in "
                    "one frame — carries the beat and keeps the video recognisable; "
                    "substitution is how the subject disappears one beat at a time."
                )

    # --- Adjacent variety --------------------------------------------------------------
    # Forbidding a repeated *subject* is what the first version of this rule did, and it
    # is incompatible with the anchor quota: the quota requires the subject repeatedly.
    # Variety has to come from how it is shot.
    for earlier, later in zip(footage, footage[1:]):
        same_scale = earlier.get("shot_scale") and earlier.get("shot_scale") == later.get(
            "shot_scale"
        )
        same_place = earlier.get("environment") and earlier.get(
            "environment"
        ) == later.get("environment")
        if same_scale and same_place:
            problems.append(
                f'{earlier.get("id")} and {later.get("id")} share both shot_scale '
                f'({earlier.get("shot_scale")!r}) and environment '
                f'({earlier.get("environment")!r}) — two adjacent visual events that look like '
                "one long shot. Change one of the two."
            )

    # --- Per-visual-event completeness ------------------------------------------------
    for beat in footage:
        label = beat.get("id") or "beat"
        queries = beat.get("queries") or []
        if len(queries) != QUERIES_PER_BEAT:
            problems.append(
                f"{label}: {len(queries)} queries, expected {QUERIES_PER_BEAT}. A third "
                "is always a paraphrase of the second, and it multiplies the download."
            )
        if not str(beat.get("camera") or "").strip():
            problems.append(
                f"{label}: no camera move. Declare one, or 'none' deliberately — an "
                "absent field reads as an oversight and renders as a static shot."
            )
        for field in ("shot_scale", "environment"):
            if not str(beat.get(field) or "").strip():
                problems.append(
                    f"{label}: no {field}. The adjacent-variety rule is measured against "
                    "it, so an absent value silently exempts the beat from that check."
                )
        if "shows_subject" not in beat:
            problems.append(
                f"{label}: no shows_subject. The anchor quota is counted from this "
                "field, and a missing value counts as false — which fails the quota "
                "rather than passing it, so this is a hard problem, not an advisory."
            )

    # --- Typographic budget ------------------------------------------------------------
    typographic = [beat for beat in beats if beat.get("typographic")]
    if typographic_budget is not None and len(typographic) > typographic_budget:
        problems.append(
            f"{len(typographic)} typographic beats against a budget of "
            f"{typographic_budget}. A typographic beat is a beat with no footage; past "
            "the budget the video stops being footage-driven."
        )

    return {
        "problems": problems,
        "advisories": advisories,
        "subject_fraction": round(fraction, 4),
        "footage_beats": len(footage_beats),
        "visual_events": len(footage),
        "uses_visual_events": has_explicit_events,
        "queries_total": queries_total,
        "sourcing_order": sourcing_order,
    }


__all__ = [
    "BANNED_QUERY_TERMS",
    "MIN_SUBJECT_FRACTION",
    "QUERIES_PER_BEAT",
    "FALLBACK_LEVELS",
    "EMOTIONAL_AFFECTS",
    "audit_scene_plan",
]
