"""Normalized observable-quality evidence for Persian production.

This module composes facts from different evidence domains without collapsing them
into one metric. Authored timeline facts, rendered-pixel measurements, and semantic
review observations keep explicit provenance and explicit limits on what they prove.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

QUALITY_EVIDENCE_VERSION = "1.0"
OPENING_SECONDS = 3.0

_DOMAINS = frozenset({"authored_timeline", "rendered_pixels", "semantic_review"})


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scope(start: float, end: float | None = None) -> dict[str, float]:
    result = {"startSeconds": round(max(0.0, float(start)), 3)}
    if end is not None:
        result["endSeconds"] = round(max(float(start), float(end)), 3)
    return result


def _record(
    *,
    kind: str,
    domain: str,
    source: str,
    observation: str,
    start: float,
    end: float | None = None,
    can_prove: Sequence[str],
    cannot_prove: Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if domain not in _DOMAINS:
        raise ValueError(f"unsupported quality-evidence domain: {domain}")
    if not kind.strip() or not source.strip() or not observation.strip():
        raise ValueError("quality evidence requires kind, source, and observation")
    return {
        "version": QUALITY_EVIDENCE_VERSION,
        "kind": kind,
        "provenance": {"domain": domain, "source": source},
        "scope": _scope(start, end),
        "observation": observation,
        "canProve": [str(item) for item in can_prove],
        "cannotProve": [str(item) for item in cannot_prove],
        **({"details": dict(details)} if details else {}),
    }


def authored_timeline_evidence(retention: Mapping[str, Any]) -> list[dict[str, Any]]:
    opening = retention.get("first3Seconds") if isinstance(retention, Mapping) else None
    opening = opening if isinstance(opening, Mapping) else {}
    records: list[dict[str, Any]] = []
    shot_events = list(opening.get("meaningfulEvents") or [])
    reveal_events = list(opening.get("overlayEvents") or [])

    for event in shot_events:
        if not isinstance(event, Mapping):
            continue
        at = _number(event.get("at"))
        records.append(_record(
            kind="authored_shot_change",
            domain="authored_timeline",
            source="persian_retention",
            observation=f"Authored shot change starts at {at:.3f}s.",
            start=at,
            can_prove=["authored_timeline_change"],
            cannot_prove=["rendered_pixel_motion", "semantic_comprehension"],
            details={"id": event.get("id"), "authoredKind": event.get("kind")},
        ))

    for event in reveal_events:
        if not isinstance(event, Mapping):
            continue
        at = _number(event.get("at"))
        records.append(_record(
            kind="authored_overlay_reveal",
            domain="authored_timeline",
            source="persian_retention",
            observation=f"Authored overlay/reveal starts at {at:.3f}s.",
            start=at,
            can_prove=["authored_timeline_change", "authored_overlay_reveal"],
            cannot_prove=["rendered_pixel_motion", "semantic_comprehension"],
            details={"id": event.get("id")},
        ))

    if not shot_events and not reveal_events:
        records.append(_record(
            kind="authored_no_post_start_change",
            domain="authored_timeline",
            source="persian_retention",
            observation=(
                f"No authored post-start shot/reveal change occurs before {OPENING_SECONDS:.1f}s."
            ),
            start=0.0,
            end=OPENING_SECONDS,
            can_prove=["absence_of_authored_post_start_shot_or_reveal_change"],
            cannot_prove=["rendered_pixel_motion", "semantic_comprehension", "perceptual_stasis"],
        ))

    grammar = retention.get("cutGrammar") if isinstance(retention, Mapping) else None
    grammar = grammar if isinstance(grammar, Mapping) else {}
    for event in list(grammar.get("events") or []):
        if not isinstance(event, Mapping):
            continue
        change = str(event.get("changeType") or "").strip()
        if not change:
            continue
        start = _number(event.get("startSeconds"))
        end = _number(event.get("endSeconds"), start)
        records.append(_record(
            kind="authored_action_label",
            domain="authored_timeline",
            source="persian_retention",
            observation=f"Authored visual-event label declares changeType={change!r}.",
            start=start,
            end=end,
            can_prove=["authored_change_intent"],
            cannot_prove=["rendered_pixel_motion", "semantic_comprehension"],
            details={
                "id": event.get("id"),
                "visualEventId": event.get("visualEventId"),
                "changeType": change,
                "narrativeRole": event.get("narrativeRole"),
            },
        ))
    return records


def rendered_motion_evidence(motion: Mapping[str, Any]) -> list[dict[str, Any]]:
    threshold = _number(motion.get("nearStaticDeltaMax"), 1.0)
    deltas = [item for item in list(motion.get("deltas") or []) if isinstance(item, Mapping)]
    opening = [
        item for item in deltas
        if 0.0 < _number(item.get("atSeconds")) <= OPENING_SECONDS
    ]
    observed = [item for item in opening if _number(item.get("meanAbsDelta")) > threshold]
    records: list[dict[str, Any]] = []
    if observed:
        first = min(_number(item.get("atSeconds")) for item in observed)
        maximum = max(_number(item.get("meanAbsDelta")) for item in observed)
        records.append(_record(
            kind="rendered_pixel_motion",
            domain="rendered_pixels",
            source="persian_motion_qa",
            observation=f"Rendered pixel motion above threshold is observed by {first:.3f}s.",
            start=0.0,
            end=OPENING_SECONDS,
            can_prove=["rendered_pixel_motion"],
            cannot_prove=["authored_timeline_change", "semantic_hook_quality", "semantic_comprehension"],
            details={
                "firstObservedAtSeconds": round(first, 3),
                "maxMeanAbsDelta": round(maximum, 3),
                "nearStaticDeltaMax": threshold,
                "sampleCountAboveThreshold": len(observed),
            },
        ))
    else:
        records.append(_record(
            kind="rendered_no_measured_motion",
            domain="rendered_pixels",
            source="persian_motion_qa",
            observation=(
                f"No sampled opening pixel delta exceeds {threshold:.3f} before {OPENING_SECONDS:.1f}s."
            ),
            start=0.0,
            end=OPENING_SECONDS,
            can_prove=["sampled_rendered_pixels_near_static_at_measurement_threshold"],
            cannot_prove=["authored_timeline_change", "semantic_hook_quality", "semantic_comprehension"],
            details={"nearStaticDeltaMax": threshold, "sampleCount": len(opening)},
        ))

    for severity, key in (("warning", "warnRuns"), ("blocking", "failRuns")):
        for raw in list(motion.get(key) or []):
            if not isinstance(raw, Mapping):
                continue
            start = _number(raw.get("startSeconds"))
            end = _number(raw.get("endSeconds"), start)
            records.append(_record(
                kind="rendered_near_static_run",
                domain="rendered_pixels",
                source="persian_motion_qa",
                observation=f"Rendered near-static run measured from {start:.3f}s to {end:.3f}s.",
                start=start,
                end=end,
                can_prove=["rendered_near_static_run"],
                cannot_prove=["authored_timeline_change", "semantic_hook_quality", "semantic_comprehension"],
                details={"severity": severity, **dict(raw)},
            ))
    return records


def cold_view_semantic_evidence(hook_review: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(hook_review, Mapping):
        return []
    raw = hook_review.get("coldViewer")
    if not isinstance(raw, Mapping):
        return []
    topic = str(raw.get("inferredTopic") or "").strip()
    claim = str(raw.get("inferredClaim") or "").strip()
    continuation = str(raw.get("continuationReason") or "").strip()
    unresolved = [str(item).strip() for item in list(raw.get("unresolvedReferents") or []) if str(item).strip()]
    understood = bool(topic and claim and continuation and not unresolved)
    return [_record(
        kind="cold_view_semantic_observation",
        domain="semantic_review",
        source="rendered_hook_cold_view",
        observation=(
            "Cold-view opening comprehension passed."
            if understood else "Cold-view opening comprehension is unresolved."
        ),
        start=0.0,
        end=OPENING_SECONDS,
        can_prove=["muted_cold_view_semantic_comprehension"],
        cannot_prove=["rendered_pixel_motion", "authored_timeline_change"],
        details={
            "comprehensionPassed": understood,
            "inferredTopic": topic,
            "inferredClaim": claim,
            "continuationReason": continuation,
            "unresolvedReferents": unresolved,
        },
    )]


def _records(raw: Mapping[str, Any], builder) -> list[dict[str, Any]]:
    existing = raw.get("observableEvidence")
    if isinstance(existing, list) and all(isinstance(item, Mapping) for item in existing):
        return [dict(item) for item in existing]
    return builder(raw)


def compose_quality_evidence(
    retention: Mapping[str, Any],
    motion: Mapping[str, Any],
    *,
    hook_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose authored, pixel, and semantic observations without relabeling them."""
    evidence = [
        *_records(retention, authored_timeline_evidence),
        *_records(motion, rendered_motion_evidence),
        *cold_view_semantic_evidence(hook_review),
    ]
    authored_kinds = {"authored_shot_change", "authored_overlay_reveal"}
    authored_change = any(
        item.get("kind") in authored_kinds
        and _number((item.get("scope") or {}).get("startSeconds")) < OPENING_SECONDS
        for item in evidence
    )
    rendered_motion_records = [
        item for item in evidence if item.get("kind") == "rendered_pixel_motion"
    ]
    rendered_motion = bool(rendered_motion_records)
    semantic = next(
        (item for item in evidence if item.get("kind") == "cold_view_semantic_observation"),
        None,
    )
    cold_value = (
        bool((semantic.get("details") or {}).get("comprehensionPassed"))
        if isinstance(semantic, Mapping) else None
    )

    statements: list[str] = []
    if authored_change:
        statements.append("Authored post-start shot/reveal change is present before 3.0s.")
    else:
        statements.append("No authored post-start shot/reveal change before 3.0s.")
    if rendered_motion:
        first = min(
            _number((item.get("details") or {}).get("firstObservedAtSeconds"), OPENING_SECONDS)
            for item in rendered_motion_records
        )
        statements.append(f"Rendered intra-shot pixel motion observed by {first:.3f}s.")
    else:
        statements.append("Rendered opening samples show no pixel motion above the configured threshold.")
    if cold_value is True:
        statements.append("Cold-view opening comprehension passed.")
    elif cold_value is False:
        statements.append("Cold-view opening comprehension is unresolved.")

    diagnostics: list[dict[str, str]] = []
    if not authored_change and rendered_motion:
        relationship = "different_provenance_not_contradictory"
        diagnostics.append({
            "code": "rendered_motion_without_authored_change",
            "severity": "info",
            "message": "The authored timeline has no post-start shot/reveal change, while rendered pixels still move inside the continuous shot.",
        })
    elif authored_change and not rendered_motion:
        relationship = "authored_change_not_observed_in_rendered_pixels"
        diagnostics.append({
            "code": "authored_change_without_rendered_motion",
            "severity": "warning",
            "message": "The timeline declares an opening shot/reveal change but sampled rendered pixels do not show motion above threshold; inspect for a frozen or ineffective render.",
        })
    elif authored_change and rendered_motion:
        relationship = "different_provenance_consistent"
    else:
        relationship = "different_provenance_both_absent"

    return {
        "version": QUALITY_EVIDENCE_VERSION,
        "evidence": evidence,
        "openingSummary": {
            "windowSeconds": OPENING_SECONDS,
            "authoredPostStartShotOrRevealChange": authored_change,
            "renderedPixelMotionObserved": rendered_motion,
            "coldViewComprehension": cold_value,
            "relationship": relationship,
            "statements": statements,
        },
        "diagnostics": diagnostics,
    }


__all__ = [
    "QUALITY_EVIDENCE_VERSION",
    "OPENING_SECONDS",
    "authored_timeline_evidence",
    "rendered_motion_evidence",
    "cold_view_semantic_evidence",
    "compose_quality_evidence",
]
