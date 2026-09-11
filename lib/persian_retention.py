"""Retention-oriented timeline audit for the Persian short-form pipeline.

This module measures facts that can be derived from the authored timeline without
pretending to judge semantics from pixels.  Human/agent judgements such as whether
the hook is compelling or the muted conclusion is understandable belong in final
review; event cadence, gaps, long uninterrupted shots, and cut grammar do not.
"""
from __future__ import annotations

from typing import Any

OPENING_WINDOW_SECONDS = 3.0
LONG_EVENT_WARNING_SECONDS = 8.0
LONG_EVENT_HIGH_RISK_SECONDS = 10.0
ENDING_TYPOGRAPHY_WARNING_SECONDS = 2.0
WINDOW_SECONDS = 15.0
EDIT_CHANGE_TYPES = ("establish", "action", "reaction", "detail", "scale_change", "punch_in")
NARRATIVE_ROLES = ("hook", "exposition", "conflict", "turn", "resolution")


def _span(item: dict[str, Any]) -> tuple[float, float]:
    return float(item.get("startSeconds") or 0.0), float(item.get("endSeconds") or 0.0)


def _merged_coverage(items: list[dict[str, Any]], duration: float) -> list[tuple[float, float]]:
    spans = []
    for item in items:
        start, end = _span(item)
        start, end = max(0.0, start), min(duration, end)
        if end > start:
            spans.append((start, end))
    spans.sort()
    merged: list[list[float]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1] + 1e-6:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(a, b) for a, b in merged]


def audit_persian_retention(persian: dict[str, Any]) -> dict[str, Any]:
    """Return measurable Reels-retention facts plus blocking problems/advisories."""
    duration = float(persian.get("durationSeconds") or 0.0)
    shots = sorted(list(persian.get("shots") or []), key=lambda s: float(s.get("startSeconds") or 0.0))
    moments = sorted(list(persian.get("moments") or []), key=lambda m: float(m.get("startSeconds") or 0.0))
    plates = sorted(list(persian.get("typographicBeats") or []), key=lambda b: float(b.get("startSeconds") or 0.0))
    problems: list[str] = []
    advisories: list[str] = []

    shot_durations = [(str(s.get("id") or "shot"), max(0.0, _span(s)[1] - _span(s)[0])) for s in shots]
    average = sum(d for _, d in shot_durations) / len(shot_durations) if shot_durations else 0.0
    longest_id, longest = max(shot_durations, key=lambda x: x[1], default=(None, 0.0))

    # Initial footage counts as the first visual event; any later shot start or
    # typographic moment in the opening window is an additional change/pattern break.
    opening_events: list[dict[str, Any]] = []
    for shot in shots:
        start, end = _span(shot)
        if start < OPENING_WINDOW_SECONDS and end > 0:
            opening_events.append({"kind": "shot", "id": shot.get("id"), "at": start})
    for moment in moments:
        start, _ = _span(moment)
        if 0 <= start < OPENING_WINDOW_SECONDS:
            opening_events.append({"kind": "moment", "id": moment.get("id"), "at": start})
    opening_events.sort(key=lambda event: (float(event["at"]), 0 if event["kind"] == "shot" else 1))
    if len(opening_events) < 2:
        problems.append(
            "first 3 seconds contain fewer than two visual events/pattern interrupts; "
            "one static footage event plus narration is a weak Reels opening"
        )

    if longest > LONG_EVENT_WARNING_SECONDS:
        level = "high retention risk" if longest > LONG_EVENT_HIGH_RISK_SECONDS else "retention risk"
        advisories.append(
            f"{longest_id} runs {longest:.2f}s without a shot change ({level}; "
            f"review the ~{LONG_EVENT_WARNING_SECONDS:.0f}-{LONG_EVENT_HIGH_RISK_SECONDS:.0f}s threshold)"
        )

    coverage = _merged_coverage(shots + plates, duration) if duration > 0 else []
    gaps: list[dict[str, float]] = []
    cursor = 0.0
    for start, end in coverage:
        if start > cursor + 1e-6:
            gaps.append({"startSeconds": round(cursor, 3), "endSeconds": round(start, 3)})
        cursor = max(cursor, end)
    if duration > cursor + 1e-6:
        gaps.append({"startSeconds": round(cursor, 3), "endSeconds": round(duration, 3)})
    if gaps:
        problems.append(f"timeline has {len(gaps)} uncovered interval(s) that can render visually empty")

    ending_text_only = 0.0
    if plates and duration > 0:
        for plate in plates:
            start, end = _span(plate)
            if abs(end - duration) <= 0.05:
                ending_text_only = max(ending_text_only, end - start)
        if ending_text_only > ENDING_TYPOGRAPHY_WARNING_SECONDS:
            advisories.append(
                f"final text-only interval is {ending_text_only:.2f}s; endings above ~1.5-2.0s "
                "are a retention risk unless intentionally justified"
            )

    transitions = []
    explicit_shots = [shot for shot in shots if shot.get("visualEventId")]
    grammar_events: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        transition = "cut" if index == 0 else str(shot.get("transitionIn") or "cut").lower()
        transitions.append(transition)
        if transition != "cut":
            problems.append(
                f"{shot.get('id')}: transitionIn={transition!r} is not executable by the current Persian renderer; "
                "hard cut is the supported default until motivated dissolve rendering exists"
            )

        if shot.get("visualEventId"):
            change_type = str(shot.get("changeType") or "").strip()
            narrative_role = str(shot.get("narrativeRole") or "").strip()
            if change_type not in EDIT_CHANGE_TYPES:
                problems.append(
                    f"{shot.get('id')}: explicit visual-event shots require changeType in "
                    + ", ".join(EDIT_CHANGE_TYPES)
                )
            if narrative_role not in NARRATIVE_ROLES:
                problems.append(
                    f"{shot.get('id')}: explicit visual-event shots require narrativeRole in "
                    + ", ".join(NARRATIVE_ROLES)
                )
            if not isinstance(shot.get("humanPresence"), bool):
                problems.append(
                    f"{shot.get('id')}: explicit visual-event shots require humanPresence true/false"
                )
            grammar_events.append(
                {
                    "id": shot.get("id"),
                    "visualEventId": shot.get("visualEventId"),
                    "changeType": change_type,
                    "narrativeRole": narrative_role,
                    "humanPresence": shot.get("humanPresence"),
                    "startSeconds": _span(shot)[0],
                    "endSeconds": _span(shot)[1],
                }
            )

    if explicit_shots:
        hook_visible = any(
            event["narrativeRole"] == "hook" and event["startSeconds"] < OPENING_WINDOW_SECONDS
            for event in grammar_events
        ) or any(
            str(moment.get("kind") or "") == "hook" and _span(moment)[0] < OPENING_WINDOW_SECONDS
            for moment in moments
        )
        if not hook_visible:
            problems.append(
                "explicit visual-event edit has no hook-labelled shot or hook moment in the first 3 seconds"
            )

        resolution_floor = duration * 0.75 if duration > 0 else 0.0
        resolution_events = [
            event for event in grammar_events
            if event["narrativeRole"] == "resolution" and event["endSeconds"] >= resolution_floor
        ]
        if not resolution_events:
            problems.append(
                "explicit visual-event edit has no resolution-labelled shot in the final quarter"
            )
        elif resolution_events[-1].get("humanPresence") is False:
            advisories.append(
                f"{resolution_events[-1]['id']}: resolution has no human presence; "
                "the Reels profile prefers a human/relatable ending when honest footage exists"
            )

        run_type = None
        run_ids: list[str] = []
        for event in grammar_events:
            if event["changeType"] and event["changeType"] == run_type:
                run_ids.append(str(event["id"]))
            else:
                if run_type and len(run_ids) >= 3:
                    advisories.append(
                        f"{', '.join(run_ids)} repeat changeType {run_type!r}; vary action/reaction/detail/scale/punch-in grammar"
                    )
                run_type = event["changeType"]
                run_ids = [str(event["id"])]
        if run_type and len(run_ids) >= 3:
            advisories.append(
                f"{', '.join(run_ids)} repeat changeType {run_type!r}; vary action/reaction/detail/scale/punch-in grammar"
            )

    changes = []
    changes.extend(float(s.get("startSeconds") or 0.0) for s in shots[1:])
    changes.extend(float(m.get("startSeconds") or 0.0) for m in moments)
    windows = []
    if duration > 0:
        start = 0.0
        while start < duration:
            end = min(duration, start + WINDOW_SECONDS)
            count = sum(1 for t in changes if start <= t < end)
            windows.append({"startSeconds": start, "endSeconds": end, "meaningfulChanges": count})
            start = end

    return {
        "problems": problems,
        "advisories": advisories,
        "first3Seconds": {"eventCount": len(opening_events), "events": opening_events},
        "averageVisualEventSeconds": round(average, 3),
        "longestVisualEvent": {"id": longest_id, "seconds": round(longest, 3)},
        "meaningfulChangesPer15Seconds": windows,
        "weakEmptyIntervals": gaps,
        "textOnlySeconds": round(sum(max(0.0, _span(b)[1] - _span(b)[0]) for b in plates), 3),
        "endingTextOnlySeconds": round(ending_text_only, 3),
        "cutGrammar": {
            "transitions": transitions,
            "nonCutCount": sum(1 for t in transitions if t != "cut"),
            "events": grammar_events,
        },
        "judgementRequired": [
            "silent_watch_main_point", "silent_watch_hook_direction", "silent_watch_conclusion",
            "strongest_scene", "weakest_scene", "hook_strength", "resolution_strength", "caption_readability",
        ],
    }


__all__ = [
    "OPENING_WINDOW_SECONDS", "LONG_EVENT_WARNING_SECONDS", "LONG_EVENT_HIGH_RISK_SECONDS",
    "ENDING_TYPOGRAPHY_WARNING_SECONDS", "EDIT_CHANGE_TYPES", "NARRATIVE_ROLES",
    "audit_persian_retention",
]
