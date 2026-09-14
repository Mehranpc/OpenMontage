"""Public structural-retention audit with opening-event semantics for short-form video."""
from __future__ import annotations

from typing import Any

from lib.persian_retention_legacy import (
    EDIT_CHANGE_TYPES,
    ENDING_TYPOGRAPHY_WARNING_SECONDS,
    LONG_EVENT_HIGH_RISK_SECONDS,
    LONG_EVENT_WARNING_SECONDS,
    NARRATIVE_ROLES,
    OPENING_WINDOW_SECONDS,
    audit_persian_retention as _audit_legacy,
)


def audit_persian_retention(persian: dict[str, Any]) -> dict[str, Any]:
    """Return structural retention evidence without treating frame zero as an event.

    The historical audit still owns coverage/cut-grammar/long-shot behaviour. This
    public seam rewrites only the opening evidence: frame zero is baseline, later
    shot starts are meaningful changes, and typographic arrivals are overlays.
    Semantic hook strength is evaluated by ``persian_hook_quality`` instead.
    """
    result = _audit_legacy(persian)
    shots = sorted(list(persian.get("shots") or []), key=lambda s: float(s.get("startSeconds") or 0.0))
    moments = sorted(list(persian.get("moments") or []), key=lambda m: float(m.get("startSeconds") or 0.0))
    baseline = next(
        (
            {"kind": "baseline_shot", "id": shot.get("id"), "at": 0.0}
            for shot in shots
            if float(shot.get("startSeconds") or 0.0) <= 1e-6
            and float(shot.get("endSeconds") or 0.0) > 0
        ),
        None,
    )
    meaningful = [
        {"kind": "shot", "id": shot.get("id"), "at": float(shot.get("startSeconds") or 0.0)}
        for shot in shots
        if 1e-6 < float(shot.get("startSeconds") or 0.0) < OPENING_WINDOW_SECONDS
    ]
    overlays = [
        {"kind": "moment", "id": moment.get("id"), "at": float(moment.get("startSeconds") or 0.0)}
        for moment in moments
        if 1e-6 < float(moment.get("startSeconds") or 0.0) < OPENING_WINDOW_SECONDS
    ]
    events = sorted(meaningful + overlays, key=lambda event: (float(event["at"]), event["kind"]))

    old_problem = "first 3 seconds contain fewer than two visual events/pattern interrupts"
    result["problems"] = [p for p in result.get("problems", []) if old_problem not in p]
    result["advisories"] = [
        a for a in result.get("advisories", []) if "first 3 seconds" not in a
    ]
    if not meaningful:
        if overlays:
            result["advisories"].append(
                "first 3 seconds have no meaningful post-start visual change; a typographic overlay is present "
                "but is not equivalent to a shot/action/reveal change"
            )
        else:
            result["advisories"].append(
                "first 3 seconds have no meaningful post-start visual change; review the opening for perceptual stasis"
            )
    result["first3Seconds"] = {
        "baselineFrameCounted": False,
        "baseline": baseline,
        "eventCount": len(events),
        "meaningfulEventCount": len(meaningful),
        "overlayEventCount": len(overlays),
        "events": events,
        "meaningfulEvents": meaningful,
        "overlayEvents": overlays,
    }
    return result


__all__ = [
    "OPENING_WINDOW_SECONDS",
    "LONG_EVENT_WARNING_SECONDS",
    "LONG_EVENT_HIGH_RISK_SECONDS",
    "ENDING_TYPOGRAPHY_WARNING_SECONDS",
    "EDIT_CHANGE_TYPES",
    "NARRATIVE_ROLES",
    "audit_persian_retention",
]
