"""Hook Quality v2 audit for Persian short-form production.

The preflight audit owns deterministic timing/evidence-shape checks and records
semantic claims, but it deliberately does not certify rendered hook strength.
Final strength belongs to an independent review of the rendered MP4.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

HOOK_QUALITY_VERSION = "2.0"
SHORT_FORM_TARGETS = frozenset({"instagram-reels", "tiktok", "youtube-shorts"})
OPENING_WINDOW_SECONDS = 3.0
VALUE_WARNING_SECONDS = 2.0
VALUE_BLOCK_SECONDS = 3.0
TENSION_WARNING_SECONDS = 2.5
TENSION_BLOCK_SECONDS = 4.0
PROOF_WARNING_SECONDS = 4.0
PROOF_BLOCK_SECONDS = 6.0
MAX_MEANINGFUL_CHANGES_FIRST_3S = 4

TENSION_KINDS = frozenset(
    {"question", "specific_gap", "contradiction", "consequence", "micro_suspense", "direct_benefit"}
)
CONCRETE_PROOF_KINDS = frozenset(
    {"answer", "result", "example", "demonstration", "evidence", "mechanism"}
)
JUDGEMENT_FIELDS = (
    "semanticPredictionError",
    "audienceRelevance",
    "concreteness",
    "hookBodyAlignment",
    "visualVoiceAlignment",
)
JUDGEMENT_LEVELS = frozenset({"weak", "acceptable", "strong"})
PERCEPTUAL_CHANGE_KINDS = frozenset(
    {"action", "reaction", "reveal", "detail", "scale_change", "punch_in", "subject_motion"}
)
_CONCEPT_LABELS = ("viewerValue", "semanticTension", "firstProof")


def _target(edit: Mapping[str, Any], persian: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    del edit
    return str(
        persian.get("platformTarget")
        or metadata.get("target_platform")
        or metadata.get("targetPlatform")
        or ""
    ).strip()


def _seconds(record: object, *, label: str, duration: float, problems: list[str]) -> float | None:
    if not isinstance(record, Mapping):
        problems.append(f"hook quality requires {label} evidence")
        return None
    raw = record.get("atSeconds")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        problems.append(f"{label}.atSeconds must be a number")
        return None
    value = float(raw)
    if value < 0 or (duration > 0 and value > duration + 1e-6):
        problems.append(f"{label}.atSeconds={value:.2f}s is outside the video timeline")
        return None
    if not str(record.get("evidence") or "").strip():
        problems.append(f"{label} requires non-empty evidence")
    return value


def _judgements(raw: object, problems: list[str]) -> dict[str, dict[str, str]]:
    """Validate authored semantic claims without treating them as final authority."""
    result: dict[str, dict[str, str]] = {}
    if not isinstance(raw, Mapping):
        problems.append("hook quality requires semantic judgements")
        return result
    for field in JUDGEMENT_FIELDS:
        item = raw.get(field)
        if not isinstance(item, Mapping):
            problems.append(f"hook judgement {field} is required")
            continue
        level = str(item.get("level") or "").strip()
        rationale = str(item.get("rationale") or "").strip()
        if level not in JUDGEMENT_LEVELS:
            problems.append(f"hook judgement {field}.level must be weak, acceptable, or strong")
            continue
        if not rationale:
            problems.append(f"hook judgement {field} requires rationale")
        result[field] = {"level": level, "rationale": rationale}
    return result


def _evidence_identity(record: object) -> tuple[str, float | None, str] | None:
    if not isinstance(record, Mapping):
        return None
    evidence_id = str(record.get("evidenceId") or "").strip()
    at = record.get("atSeconds")
    at_value = float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else None
    text = " ".join(str(record.get("evidence") or "").split()).casefold()
    return evidence_id, at_value, text


def _shared_justifications(hook: Mapping[str, Any], problems: list[str]) -> dict[str, list[dict[str, Any]]]:
    raw = hook.get("sharedEvidenceJustifications") or []
    if not isinstance(raw, list):
        problems.append("hookQuality.sharedEvidenceJustifications must be an array when present")
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            problems.append(f"shared evidence justification {index} must be an object")
            continue
        evidence_id = str(item.get("evidenceId") or "").strip()
        concepts = item.get("concepts")
        justification = str(item.get("justification") or "").strip()
        if not evidence_id:
            problems.append(f"shared evidence justification {index} requires evidenceId")
            continue
        if not isinstance(concepts, list) or len(set(str(x) for x in concepts)) < 2:
            problems.append(f"shared evidence justification {index} must name at least two concepts")
            continue
        clean = [str(x) for x in concepts]
        if any(concept not in _CONCEPT_LABELS for concept in clean):
            problems.append(f"shared evidence justification {index} names an unsupported concept")
            continue
        if not justification:
            problems.append(f"shared evidence justification {index} requires justification")
            continue
        result.setdefault(evidence_id, []).append(
            {"concepts": clean, "justification": justification}
        )
    return result


def _has_shared_justification(
    justifications: Mapping[str, list[dict[str, Any]]], evidence_id: str, left: str, right: str
) -> bool:
    if not evidence_id:
        return False
    pair = {left, right}
    return any(pair.issubset(set(item["concepts"])) for item in justifications.get(evidence_id, []))


def _validate_distinct_semantic_evidence(
    hook: Mapping[str, Any], records: Mapping[str, object], problems: list[str]
) -> dict[str, list[dict[str, Any]]]:
    justifications = _shared_justifications(hook, problems)
    labels = list(records)
    for index, left in enumerate(labels):
        left_identity = _evidence_identity(records[left])
        if left_identity is None:
            continue
        left_id, left_at, left_text = left_identity
        for right in labels[index + 1 :]:
            right_identity = _evidence_identity(records[right])
            if right_identity is None:
                continue
            right_id, right_at, right_text = right_identity
            same_id = bool(left_id and right_id and left_id == right_id)
            same_observation = (
                left_at is not None
                and right_at is not None
                and abs(left_at - right_at) <= 1e-6
                and bool(left_text)
                and left_text == right_text
            )
            if not (same_id or same_observation):
                continue
            evidence_id = left_id if same_id else ""
            if not _has_shared_justification(justifications, evidence_id, left, right):
                problems.append(
                    f"{left} and {right} use shared evidence without an explicit justification; "
                    "distinct editorial functions cannot be double-counted automatically"
                )
    return justifications


def _concrete_proof_seconds(
    record: object, *, duration: float, problems: list[str]
) -> float | None:
    value = _seconds(record, label="first proof", duration=duration, problems=problems)
    if not isinstance(record, Mapping):
        return None
    kind = str(record.get("kind") or "").strip()
    if kind not in CONCRETE_PROOF_KINDS:
        problems.append(
            "first proof must be a concrete answer, result, example, demonstration, evidence, or mechanism; "
            "authority/setup language such as 'research shows' is not concrete proof"
        )
        return None
    return value


def _perceptual_evidence(
    persian: Mapping[str, Any],
    hook: Mapping[str, Any] | None,
    advisories: list[str],
    problems: list[str],
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    shots = sorted(
        list(persian.get("shots") or []),
        key=lambda shot: float(shot.get("startSeconds") or 0.0),
    )
    for shot in shots:
        start = float(shot.get("startSeconds") or 0.0)
        if 1e-6 < start < OPENING_WINDOW_SECONDS:
            changes.append(
                {"kind": "shot_change", "atSeconds": start, "source": str(shot.get("id") or "shot")}
            )

    if hook is not None:
        authored = hook.get("perceptualChanges") or []
        if not isinstance(authored, list):
            problems.append("hookQuality.perceptualChanges must be an array when present")
        else:
            for index, item in enumerate(authored):
                if not isinstance(item, Mapping):
                    problems.append(f"hookQuality.perceptualChanges[{index}] must be an object")
                    continue
                kind = str(item.get("kind") or "").strip()
                raw_at = item.get("atSeconds")
                evidence = str(item.get("evidence") or "").strip()
                if kind not in PERCEPTUAL_CHANGE_KINDS:
                    problems.append(f"hook perceptual change {index} has unsupported kind {kind!r}")
                    continue
                if not isinstance(raw_at, (int, float)) or isinstance(raw_at, bool) or float(raw_at) <= 0:
                    problems.append(f"hook perceptual change {index} requires atSeconds > 0")
                    continue
                at = float(raw_at)
                if at >= OPENING_WINDOW_SECONDS:
                    continue
                if not evidence:
                    problems.append(f"hook perceptual change {index} requires evidence")
                changes.append({"kind": kind, "atSeconds": at, "source": "authored", "evidence": evidence})

    changes.sort(key=lambda item: float(item["atSeconds"]))
    moments = sorted(
        list(persian.get("moments") or []),
        key=lambda moment: float(moment.get("startSeconds") or 0.0),
    )
    overlays = [
        {"id": moment.get("id"), "atSeconds": float(moment.get("startSeconds") or 0.0)}
        for moment in moments
        if 1e-6 < float(moment.get("startSeconds") or 0.0) < OPENING_WINDOW_SECONDS
    ]
    if not changes:
        advisories.append(
            "first 3 seconds have no evidenced meaningful post-start perceptual change; "
            "typography alone is not treated as a shot/action/reveal change"
        )
    if len(changes) > MAX_MEANINGFUL_CHANGES_FIRST_3S:
        advisories.append(
            f"first 3 seconds contain {len(changes)} meaningful changes; review for chaotic over-editing"
        )
    return {
        "firstMeaningfulVisualChangeSeconds": round(float(changes[0]["atSeconds"]), 3) if changes else None,
        "meaningfulChangeCountFirst3Seconds": len(changes),
        "meaningfulChanges": changes,
        "overlayEventCountFirst3Seconds": len(overlays),
        "overlayEvents": overlays,
        "baselineFrameCountsAsChange": False,
    }


def _policy() -> dict[str, Any]:
    return {
        "version": HOOK_QUALITY_VERSION,
        "openingWindowSeconds": OPENING_WINDOW_SECONDS,
        "valueWarningSeconds": VALUE_WARNING_SECONDS,
        "valueBlockSeconds": VALUE_BLOCK_SECONDS,
        "tensionWarningSeconds": TENSION_WARNING_SECONDS,
        "tensionBlockSeconds": TENSION_BLOCK_SECONDS,
        "proofWarningSeconds": PROOF_WARNING_SECONDS,
        "proofBlockSeconds": PROOF_BLOCK_SECONDS,
        "maxMeaningfulChangesFirst3Seconds": MAX_MEANINGFUL_CHANGES_FIRST_3S,
        "thresholdStatus": "initial-conservative-calibration",
        "predictsVirality": False,
        "renderedReviewRequiredForFinalStrength": True,
    }


def audit_persian_hook_quality(edit: Mapping[str, Any]) -> dict[str, Any]:
    """Audit Hook Quality v2 planning evidence before browser/render work."""
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    metadata = edit.get("metadata") if isinstance(edit.get("metadata"), Mapping) else {}
    duration = float(persian.get("durationSeconds") or 0.0)
    target = _target(edit, persian, metadata)
    required = target in SHORT_FORM_TARGETS
    raw_hook = metadata.get("hookQuality")
    hook = raw_hook if isinstance(raw_hook, Mapping) else None
    problems: list[str] = []
    advisories: list[str] = []

    if raw_hook is not None and hook is None:
        problems.append("metadata.hookQuality must be an object")
    if hook is None:
        perceptual = _perceptual_evidence(persian, None, advisories, problems)
        if required:
            problems.append(
                f"{target} production requires metadata.hookQuality evidence before browser preflight"
            )
        return {
            "version": HOOK_QUALITY_VERSION,
            "required": required,
            "platformTarget": target or None,
            "disposition": "weak" if problems else "unassessed",
            "problems": problems,
            "advisories": advisories,
            "timing": {
                "timeToValueSeconds": None,
                "timeToSemanticTensionSeconds": None,
                "timeToFirstProofSeconds": None,
            },
            "perceptual": perceptual,
            "judgements": {},
            "flags": {},
            "semanticAuthority": "authored-claim-awaiting-rendered-review",
            "policy": _policy(),
        }

    if str(hook.get("version") or "") != HOOK_QUALITY_VERSION:
        problems.append(f"metadata.hookQuality.version must be {HOOK_QUALITY_VERSION}")

    viewer_value_record = hook.get("viewerValue")
    if viewer_value_record is None and hook.get("valueProposition") is not None:
        problems.append("Hook Quality v2 requires viewerValue; valueProposition is legacy v1 metadata")
        viewer_value_record = hook.get("valueProposition")
    value = _seconds(
        viewer_value_record,
        label="viewer value",
        duration=duration,
        problems=problems,
    )
    tension_record = hook.get("semanticTension")
    tension = _seconds(tension_record, label="semantic tension", duration=duration, problems=problems)
    proof_record = hook.get("firstProof")
    proof = _concrete_proof_seconds(proof_record, duration=duration, problems=problems)

    tension_kind = str(tension_record.get("kind") or "").strip() if isinstance(tension_record, Mapping) else ""
    if tension_kind not in TENSION_KINDS:
        problems.append(
            "semantic tension kind must identify a specific gap, contradiction, consequence, suspense, or benefit"
        )

    _validate_distinct_semantic_evidence(
        hook,
        {
            "viewerValue": viewer_value_record,
            "semanticTension": tension_record,
            "firstProof": proof_record,
        },
        problems,
    )

    if value is not None:
        if value > VALUE_BLOCK_SECONDS:
            problems.append(
                f"viewer value arrives at {value:.2f}s, after the {VALUE_BLOCK_SECONDS:.1f}s initial blocking ceiling"
            )
        elif value > VALUE_WARNING_SECONDS:
            advisories.append(f"viewer value arrives late at {value:.2f}s")
    if tension is not None:
        if tension > TENSION_BLOCK_SECONDS:
            problems.append(
                f"semantic tension arrives at {tension:.2f}s, after the {TENSION_BLOCK_SECONDS:.1f}s initial blocking ceiling"
            )
        elif tension > TENSION_WARNING_SECONDS:
            advisories.append(f"semantic tension arrives late at {tension:.2f}s")
    if proof is not None:
        if proof > PROOF_BLOCK_SECONDS:
            problems.append(
                f"first concrete proof/payoff arrives at {proof:.2f}s, after the {PROOF_BLOCK_SECONDS:.1f}s initial blocking ceiling"
            )
        elif proof > PROOF_WARNING_SECONDS:
            advisories.append(f"first concrete proof/payoff arrives late at {proof:.2f}s")

    judgements = _judgements(hook.get("judgements"), problems)
    for field in ("audienceRelevance", "hookBodyAlignment", "visualVoiceAlignment"):
        if (judgements.get(field) or {}).get("level") == "weak":
            problems.append(f"hook judgement {field} is weak")
    for field in ("semanticPredictionError", "concreteness"):
        if (judgements.get(field) or {}).get("level") == "weak":
            advisories.append(f"hook judgement {field} is weak")

    raw_flags = hook.get("flags") or {}
    if not isinstance(raw_flags, Mapping):
        problems.append("hookQuality.flags must be an object")
        flags: dict[str, bool] = {}
    else:
        flags = {}
        for key in ("metaIntroDelay", "vagueGap", "fullConclusionRevealed"):
            flag_value = raw_flags.get(key, False)
            if not isinstance(flag_value, bool):
                problems.append(f"hookQuality.flags.{key} must be boolean")
                continue
            flags[key] = flag_value
    if flags.get("metaIntroDelay"):
        advisories.append("opening contains value-delaying meta-intro language")
    if flags.get("vagueGap"):
        problems.append("hook information gap is too vague to identify a reachable missing answer")
    if flags.get("fullConclusionRevealed"):
        advisories.append(
            "opening reveals the full conclusion; verify that another concrete reason to continue remains"
        )

    perceptual = _perceptual_evidence(persian, hook, advisories, problems)
    # Authored prose is planning evidence only. It may block obviously weak work,
    # but it can never self-certify a production as strong before rendered review.
    disposition = "weak" if problems else "acceptable"

    return {
        "version": HOOK_QUALITY_VERSION,
        "required": required,
        "platformTarget": target or None,
        "disposition": disposition,
        "problems": problems,
        "advisories": advisories,
        "timing": {
            "timeToValueSeconds": round(value, 3) if value is not None else None,
            "timeToSemanticTensionSeconds": round(tension, 3) if tension is not None else None,
            "timeToFirstProofSeconds": round(proof, 3) if proof is not None else None,
            "semanticTensionKind": tension_kind or None,
        },
        "perceptual": perceptual,
        "judgements": judgements,
        "flags": flags,
        "semanticAuthority": "authored-claim-awaiting-rendered-review",
        "policy": _policy(),
    }


__all__ = [
    "HOOK_QUALITY_VERSION",
    "SHORT_FORM_TARGETS",
    "CONCRETE_PROOF_KINDS",
    "audit_persian_hook_quality",
]
