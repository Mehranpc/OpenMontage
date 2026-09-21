"""Deterministic recovery policy for Persian production preflight.

Issue #28 keeps recovery bounded *and* gives every class an explicit mutation
surface. A recovery strategy may not spend an unrelated editorial budget simply
because its own constraint is difficult to satisfy.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RECOVERY_POLICY_VERSION = "2.1"

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
        "strategies": ["select_already_acquired_opening_asset", "adjust_opening_source_window"],
        "mutationSurface": ["opening.existing_asset_selection", "opening.source_window"],
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
        "strategies": ["use_authored_alternate_query", "stop_for_editorial_revision"],
        "mutationSurface": ["assets.selection", "assets.query"],
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
    "known_recovery_classes",
]
