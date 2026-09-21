from __future__ import annotations

from pathlib import Path

import pytest

import lib.persian_preflight as preflight
import lib.persian_video_workflow as workflow
import schemas.artifacts as artifacts
from lib.persian_rendered_review import PersianRenderedReviewError, validate_rendered_hook_review
from tests.lib.test_persian_preflight_contract import _payload


DIGEST = "a" * 64


def _semantic_pass_with_visual(**visual_overrides) -> dict:
    visual = {
        "policyVersion": "1.0",
        "evidenceSource": "rendered_opening_pixels",
        "hierarchyPassed": True,
        "occupancyRatio": 0.31,
        "emphasisPassed": True,
        "lineBalancePassed": True,
        "opticalPlacementPassed": True,
        "durationSeconds": 3.2,
        "recipeId": "editorial-hero-balanced",
    }
    visual.update(visual_overrides)
    return {
        "version": "2.1",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": DIGEST,
        "strength": "strong",
        "rationale": "The semantic hook is concrete and resolves promptly.",
        "observations": ["The topic is recoverable muted.", "The contradiction remains unresolved long enough to continue."],
        "mutedHookDirectionConfirmed": True,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "بازی‌های ویدیویی",
            "inferredClaim": "فقط وقت تلف کردن نیست",
            "continuationReason": "نتیجه هنوز کامل نشده",
            "unresolvedReferents": [],
        },
        "visualVoiceAlignment": "strong",
        "actualPayoffSeconds": 4.8,
        "concretePayoffKind": "result",
        "payoffEvidence": "A concrete result starts before the semantic deadline.",
        "payoffBeginsPromptly": True,
        "timingPolicyVersion": "2.1",
        "timingDisposition": "prompt",
        "authorityProvenance": {
            "mode": "automatic",
            "reference": "workflow.hook_selection",
            "selectedHookSha256": "c" * 64,
        },
        "visualTypography": visual,
    }


def test_front_door_has_opening_gate_and_mastering_before_final_review() -> None:
    phases = workflow.PHASES
    assert phases.index("no_copy_preflight") < phases.index("render_opening_candidate")
    assert phases.index("render_opening_candidate") < phases.index("opening_review")
    assert phases.index("opening_review") < phases.index("render_final_candidate")
    assert phases.index("render_final_candidate") < phases.index("master_final_candidate")
    assert phases.index("master_final_candidate") < phases.index("final_review")
    assert phases.index("final_review") < phases.index("awaiting_human")


def test_watermark_preflight_is_subject_geometry_agnostic(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["persian"]["durationSeconds"] = 20.0
    payload["persian"]["shots"][0]["endSeconds"] = 20.0
    payload["persian"]["shots"][0]["avoidRegions"] = [
        {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "startSeconds": 5.0, "endSeconds": 20.0}
    ]
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda _: {"problems": []})
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda _: {"version": "2.0", "required": False, "problems": [], "advisories": []})
    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", lambda *a, **k: {"warnings": [], "watermarkDiagnostics": None})

    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)

    assert report["ok"] is True
    assert report["evidence"]["watermarkPolicy"]["subjectGeometryAgnostic"] is True
    assert not any(item["code"] == "WATERMARK_GLOBAL_FEASIBILITY" for item in report["blockingIssues"])


def test_visual_typography_can_fail_even_when_semantic_hook_is_strong() -> None:
    validate_rendered_hook_review(_semantic_pass_with_visual(), candidate_sha256=DIGEST, require_pass=True)
    with pytest.raises(PersianRenderedReviewError, match="visual typography"):
        validate_rendered_hook_review(
            _semantic_pass_with_visual(hierarchyPassed=False, occupancyRatio=0.08),
            candidate_sha256=DIGEST,
            require_pass=True,
        )


def test_workflow_exposes_four_distinct_runtime_metrics() -> None:
    accounting = workflow.phase_time_accounting({"phase_telemetry": {}})
    assert set(("job_runtime_seconds", "provider_wait_seconds", "accounting_lag_seconds", "editorial_wall_seconds")).issubset(accounting)


def test_safe_zero_length_timing_repair_is_a_first_class_front_door_helper() -> None:
    repair = getattr(workflow, "repair_trivial_zero_length_timings", None)
    assert callable(repair)
    repaired = repair([
        {"word": "بازی", "start": 1.0, "end": 1.0},
        {"word": "فقط", "start": 1.2, "end": 1.5},
    ])
    assert repaired[0]["end"] > repaired[0]["start"]
    assert repaired[0]["end"] <= repaired[1]["start"]


def test_artifact_contract_exposes_canonical_builder_from_schema_source() -> None:
    builder = getattr(artifacts, "build_artifact", None)
    contract = getattr(artifacts, "artifact_contract", None)
    assert callable(builder)
    assert callable(contract)
    spec = contract("final_review")
    assert spec["requiredFields"]
    assert spec["cliHelp"]
