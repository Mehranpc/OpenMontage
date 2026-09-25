"""Deterministic recovery policy for Persian production preflight.

Issue #28 keeps recovery bounded *and* gives every class an explicit mutation
surface. A recovery strategy may not spend an unrelated editorial budget simply
because its own constraint is difficult to satisfy.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RECOVERY_POLICY_VERSION = "2.3"

_CLASS_POLICIES: dict[str, dict[str, Any]] = {
    "HOOK_SEMANTIC": {
        "maxAttempts": 2,
        "strategies": [
            "restore_required_topic_anchor_in_viewer_visible_hook",
            "establish_required_anchor_with_reviewed_opening_visual_if_not_typographic_only",
        ],
        "mutationSurface": ["hook.semantic_copy", "hook.semantic_evidence", "opening.existing_asset_selection"],
        "preserve": ["approved_script", "narration", "asset_budget", "audio_mix"],
    },
    "HOOK_AUTHORING": {
        "maxAttempts": 2,
        "strategies": ["revise_hook_copy_only", "revise_hook_semantic_evidence_only"],
        "mutationSurface": ["hook.semantic_copy", "hook.semantic_evidence"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "HOOK_TIMING": {
        "maxAttempts": 2,
        "strategies": ["retime_hook_window_only", "retime_first_payoff_only"],
        "mutationSurface": ["hook.duration", "hook.payoff_timing"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "HOOK_VISUAL_ALIGNMENT": {
        "maxAttempts": 2,
        "strategies": [
            "select_already_acquired_opening_asset",
            "adjust_opening_source_window",
            "revise_hook_visual_evidence_only",
        ],
        "mutationSurface": [
            "opening.existing_asset_selection",
            "opening.source_window",
            "hook.visual_evidence",
        ],
        "preserve": ["approved_script", "narration", "audio_mix", "asset_budget"],
    },
    "CAPTION_CONTINUITY": {
        "maxAttempts": 2,
        "strategies": [
            "set_semantic_replacement_resume_to_next_complete_unit",
            "regroup_opening_caption_semantic_boundary",
        ],
        "mutationSurface": ["captions.semantic_handoff", "captions.cue_grouping"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "CAPTION_WRAP": {
        "maxAttempts": 2,
        "strategies": ["regroup_caption_cue_boundaries", "choose_alternate_phrase_safe_line_break"],
        "mutationSurface": ["captions.cue_grouping", "captions.line_breaks"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "TIMELINE_GRID": {
        "maxAttempts": 1,
        "strategies": ["quantize_visual_timeline_boundaries_to_30fps_grid"],
        "mutationSurface": ["timeline.frame_boundaries"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "WATERMARK_TIMING": {
        "maxAttempts": 2,
        "strategies": [
            "use_approved_fixed_anchor_schedule",
            "suppress_minimum_subtitle_collision_interval",
        ],
        "mutationSurface": ["watermark.schedule", "watermark.suppression"],
        "preserve": [
            "approved_script", "narration", "assets", "audio_mix", "scenes",
            "subject_regions", "typography", "copy",
        ],
    },
    "FILM_TYPE_LAYOUT": {
        "maxAttempts": 3,
        "strategies": [
            "select_curated_typography_recipe",
            "rebalance_measured_line_plan",
            "adjust_editorial_hold_within_policy",
            "retime_reveal_schedule_within_readability_policy",
        ],
        "mutationSurface": [
            "typography.recipe",
            "typography.line_plan",
            "typography.duration",
            "timeline.reveal_schedule",
        ],
        "preserve": [
            "approved_script", "narration", "assets", "audio_mix", "scenes",
            "subject_regions", "watermark",
        ],
    },
    "SUBJECT_REGION_REVIEW": {
        "maxAttempts": 1,
        "strategies": ["attach_reviewed_subject_regions"],
        # The candidate still declares every concrete changed field. The wildcard
        # lets the existing convergence workspace carry this newly named scope
        # without widening behavior: every other dependency scope is explicitly
        # frozen below, so only subject_regions may differ from the parent.
        "mutationSurface": ["diagnostic.named_contract_field"],
        "preserve": [
            "approved_script", "narration", "hook", "captions", "timeline",
            "watermark", "typography", "assets", "scenes", "audio_mix", "copy",
            "unclassified",
        ],
    },
    "ASSET_SELECTION": {
        "maxAttempts": 2,
        "strategies": [
            "reuse_reviewed_non_overlapping_source_window",
            "reuse_reviewed_existing_candidate",
            "use_authored_alternate_query",
            "stop_for_editorial_revision",
        ],
        "mutationSurface": [
            "assets.selection", "assets.query", "subject_regions.review",
            "hook.visual_evidence", "scenes.asset_dependent_metadata",
        ],
        "preserve": ["approved_script", "narration", "audio_mix", "copy"],
    },
    "PREFLIGHT_RUNTIME": {
        "maxAttempts": 1,
        "strategies": ["retry_same_digest_after_runtime_or_reporting_repair"],
        "mutationSurface": ["runtime.reporting"],
        "preserve": ["approved_script", "narration", "assets", "edit_digest"],
    },
    "EDIT_ARTIFACT": {
        "maxAttempts": 2,
        "strategies": ["repair_reported_contract_field_only", "stop_for_editorial_revision"],
        "mutationSurface": ["diagnostic.named_contract_field"],
        "preserve": ["unrelated_artifacts"],
    },
}

_CODE_PREFIX_CLASS = (
    ("HOOK_TOPIC_ANCHOR_", "HOOK_SEMANTIC"),
    ("HOOK_SEMANTIC_INTEGRITY_", "HOOK_SEMANTIC"),
    ("HOOK_TYPOGRAPHIC_DURATION_", "HOOK_TIMING"),
    ("CAPTION_HANDOFF_", "CAPTION_CONTINUITY"),
    ("CAPTION_WRAP_", "CAPTION_WRAP"),
    ("TIMELINE_FRAME_", "TIMELINE_GRID"),
    ("WATERMARK_", "WATERMARK_TIMING"),
    ("SUBJECT_REGION_", "SUBJECT_REGION_REVIEW"),
    ("ASSET_SELECTION_", "ASSET_SELECTION"),
    ("FILM_TYPE_", "FILM_TYPE_LAYOUT"),
)


def recovery_class_for_code(code: object, fallback: str | None = None) -> str:
    value = str(code or "").strip().upper()
    for prefix, recovery_class in _CODE_PREFIX_CLASS:
        if value.startswith(prefix):
            return recovery_class
    return str(fallback or "EDIT_ARTIFACT")


def recovery_policy_for_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    code = str(issue.get("code") or "UNKNOWN").strip().upper()
    recovery_class = recovery_class_for_code(code, str(issue.get("recoveryClass") or ""))
    policy = _CLASS_POLICIES.get(recovery_class, _CLASS_POLICIES["EDIT_ARTIFACT"])
    return {
        "version": RECOVERY_POLICY_VERSION,
        "diagnosticCode": code,
        "recoveryClass": recovery_class,
        "maxAttempts": int(policy["maxAttempts"]),
        "strategies": list(policy["strategies"]),
        "mutationSurface": list(policy["mutationSurface"]),
        "preserve": list(policy["preserve"]),
        "exhaustedOutcome": "needs_human_editorial_revision",
    }


def shot_local_recovery_plan(
    issue: Mapping[str, Any],
    edit_decisions: Mapping[str, Any],
    asset_workspace: Mapping[str, Any],
) -> dict[str, Any]:
    """Plan local-first fit/asset recovery without widening the affected shot set."""
    code = str(issue.get("code") or "UNKNOWN").strip().upper()
    recovery_class = recovery_class_for_code(code, str(issue.get("recoveryClass") or ""))
    if recovery_class not in {"FILM_TYPE_LAYOUT", "ASSET_SELECTION"}:
        raise ValueError(
            f"shot-local recovery is only defined for FILM_TYPE_LAYOUT/ASSET_SELECTION; got {recovery_class}"
        )

    details = issue.get("details") if isinstance(issue.get("details"), Mapping) else {}
    raw_shot_ids = details.get("shotIds") if isinstance(details, Mapping) else None
    if raw_shot_ids is None:
        raw_shot_ids = issue.get("shotIds")
    if raw_shot_ids is None:
        raw_shot_ids = []
    if not isinstance(raw_shot_ids, list) or any(not str(item).strip() for item in raw_shot_ids):
        raise ValueError("shot-local recovery requires shotIds as a list of non-empty ids")
    shot_ids = list(dict.fromkeys(str(item).strip() for item in raw_shot_ids))
    if recovery_class == "ASSET_SELECTION" and not shot_ids:
        raise ValueError("ASSET_SELECTION recovery requires affected shotIds")

    persian = edit_decisions.get("persian") if isinstance(edit_decisions.get("persian"), Mapping) else {}
    raw_shots = persian.get("shots") if isinstance(persian, Mapping) else None
    if not isinstance(raw_shots, list):
        raise ValueError("edit_decisions.persian.shots is required for shot-local recovery")
    shots = {
        str(shot.get("id") or "").strip(): shot
        for shot in raw_shots
        if isinstance(shot, Mapping) and str(shot.get("id") or "").strip()
    }
    missing = [shot_id for shot_id in shot_ids if shot_id not in shots]
    if missing:
        raise ValueError("shot-local recovery references unknown shot ids: " + ", ".join(missing))

    if recovery_class == "FILM_TYPE_LAYOUT":
        return {
            "version": "1.0",
            "diagnosticCode": code,
            "recoveryClass": recovery_class,
            "decision": "same_phase_repair",
            "sendBackAllowed": False,
            "affectedShotIds": shot_ids,
            "localRepairShotIds": shot_ids,
            "reacquireShotIds": [],
            "reacquireVisualEventIds": [],
            "existingOptions": {},
            "reasonCode": "LAYOUT_REPAIR_REQUIRED_BEFORE_ASSET_REACQUISITION",
        }

    selected = asset_workspace.get("selectedCandidateIds")
    reusable = asset_workspace.get("reusableCandidatesByVisualEvent")
    selected = dict(selected) if isinstance(selected, Mapping) else {}
    reusable = dict(reusable) if isinstance(reusable, Mapping) else {}
    local: list[str] = []
    reacquire: list[str] = []
    reacquire_events: list[str] = []
    existing_options: dict[str, list[dict[str, Any]]] = {}

    for shot_id in shot_ids:
        shot = shots[shot_id]
        event_id = str(shot.get("visualEventId") or "").strip()
        if not event_id:
            raise ValueError(f"{shot_id} requires visualEventId for asset recovery")
        selected_id = str(selected.get(event_id) or "")
        event_candidates = reusable.get(event_id)
        event_candidates = event_candidates if isinstance(event_candidates, list) else []
        selected_source = ""
        for item in event_candidates:
            if not isinstance(item, Mapping) or str(item.get("candidateId") or "") != selected_id:
                continue
            identity = item.get("identity") if isinstance(item.get("identity"), Mapping) else {}
            selected_source = str(identity.get("sourceId") or "")
            break
        alternates: list[dict[str, Any]] = []
        for item in event_candidates:
            if not isinstance(item, Mapping):
                continue
            candidate_id = str(item.get("candidateId") or "").strip()
            if not candidate_id or candidate_id == selected_id:
                continue
            identity = item.get("identity") if isinstance(item.get("identity"), Mapping) else {}
            source_id = str(identity.get("sourceId") or "")
            alternates.append({
                "candidateId": candidate_id,
                "sourceId": source_id,
                "sameSourceAsSelected": bool(selected_source and source_id == selected_source),
                "candidateRank": int(item.get("candidateRank") or 999999),
                "identity": dict(identity),
            })
        alternates.sort(key=lambda item: (
            not item["sameSourceAsSelected"], item["candidateRank"], item["candidateId"]
        ))
        existing_options[shot_id] = alternates
        if alternates:
            local.append(shot_id)
        else:
            reacquire.append(shot_id)
            reacquire_events.append(event_id)

    return {
        "version": "1.0",
        "diagnosticCode": code,
        "recoveryClass": recovery_class,
        "decision": "scoped_asset_reacquisition" if reacquire else "same_phase_repair",
        "sendBackAllowed": bool(reacquire),
        "affectedShotIds": shot_ids,
        "localRepairShotIds": local,
        "reacquireShotIds": reacquire,
        "reacquireVisualEventIds": list(dict.fromkeys(reacquire_events)),
        "existingOptions": existing_options,
        "reasonCode": (
            "EXISTING_ASSET_OPTIONS_EXHAUSTED_FOR_SCOPED_SHOTS"
            if reacquire else "REUSE_EXISTING_REVIEWED_ASSET_OPTION"
        ),
    }


def recovery_budget_for_class(recovery_class: str) -> int:
    policy = _CLASS_POLICIES.get(str(recovery_class), _CLASS_POLICIES["EDIT_ARTIFACT"])
    return int(policy["maxAttempts"])


def known_recovery_classes() -> tuple[str, ...]:
    return tuple(_CLASS_POLICIES)


__all__ = [
    "RECOVERY_POLICY_VERSION",
    "recovery_class_for_code",
    "recovery_policy_for_issue",
    "recovery_budget_for_class",
    "shot_local_recovery_plan",
    "known_recovery_classes",
]
