"""Deterministic recovery policy for Persian production preflight.

Issue #26 makes recovery a bounded engineering contract rather than an open-ended
agent loop. Diagnostics map to one recovery class, a finite ordered strategy list,
and a hard per-class attempt ceiling. The policy never edits artifacts itself; it
constrains the orchestrator so unrelated dimensions stay frozen during repair.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RECOVERY_POLICY_VERSION = "1.0"

_CLASS_POLICIES: dict[str, dict[str, Any]] = {
    "HOOK_SEMANTIC": {
        "maxAttempts": 2,
        "strategies": [
            "restore_required_topic_anchor_in_viewer_visible_hook",
            "establish_required_anchor_with_reviewed_opening_visual_if_not_typographic_only",
        ],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "HOOK_AUTHORING": {
        "maxAttempts": 2,
        "strategies": ["revise_hook_copy_only", "revise_hook_semantic_evidence_only"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "HOOK_TIMING": {
        "maxAttempts": 2,
        "strategies": ["retime_hook_window_only", "retime_first_payoff_only"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "HOOK_VISUAL_ALIGNMENT": {
        "maxAttempts": 2,
        "strategies": ["select_already_acquired_opening_asset", "adjust_opening_source_window"],
        "preserve": ["approved_script", "narration", "audio_mix"],
    },
    "CAPTION_CONTINUITY": {
        "maxAttempts": 2,
        "strategies": [
            "set_semantic_replacement_resume_to_next_complete_unit",
            "regroup_opening_caption_semantic_boundary",
        ],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "CAPTION_WRAP": {
        "maxAttempts": 2,
        "strategies": ["regroup_caption_cue_boundaries", "choose_alternate_phrase_safe_line_break"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "TIMELINE_GRID": {
        "maxAttempts": 1,
        "strategies": ["quantize_visual_timeline_boundaries_to_30fps_grid"],
        "preserve": ["approved_script", "narration", "assets", "audio_mix"],
    },
    "WATERMARK_TIMING": {
        "maxAttempts": 3,
        "strategies": [
            "use_planner_best_schedule",
            "adjust_watermark_safe_timing_without_lowering_coverage_floor",
            "replace_only_blocking_footage_window_if_required",
        ],
        "preserve": ["approved_script", "narration", "audio_mix"],
    },
    "FILM_TYPE_LAYOUT": {
        "maxAttempts": 3,
        "strategies": [
            "apply_deterministic_layout_alternative",
            "adjust_text_placement_or_width_without_rewriting_copy",
            "replace_only_geometry_blocking_asset_if_required",
        ],
        "preserve": ["approved_script", "narration", "audio_mix"],
    },
    "ASSET_SELECTION": {
        "maxAttempts": 2,
        "strategies": ["use_authored_alternate_query", "stop_for_editorial_revision"],
        "preserve": ["approved_script", "narration", "audio_mix"],
    },
    "PREFLIGHT_RUNTIME": {
        "maxAttempts": 1,
        "strategies": ["retry_same_digest_after_runtime_or_reporting_repair"],
        "preserve": ["approved_script", "narration", "assets", "edit_digest"],
    },
    "EDIT_ARTIFACT": {
        "maxAttempts": 2,
        "strategies": ["repair_reported_contract_field_only", "stop_for_editorial_revision"],
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
