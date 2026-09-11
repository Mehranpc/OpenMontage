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
