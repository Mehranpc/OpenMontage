from __future__ import annotations

import hashlib
import json

import pytest

from lib.persian_rendered_review import build_cold_viewer_review_input
from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase
from tests.lib.test_persian_video_workflow import BASE, _checkpoint, _review_ready_project


def _hook_audit() -> dict:
    return {
        "version": "2.0",
        "required": True,
        "disposition": "acceptable",
        "problems": [],
        "advisories": [],
        "semanticAuthority": "authored-claim-awaiting-rendered-review",
    }


def _cold_viewer(*, understood: bool = True) -> dict:
    return {
        "evidenceSource": "rendered_opening_only",
        "contextIsolated": True,
        "inferredTopic": "موضوع مشخص افتتاحیه" if understood else "",
        "inferredClaim": "ادعای مشخص افتتاحیه" if understood else "",
        "continuationReason": "پاسخ هنوز کامل نشده است" if understood else "",
        "unresolvedReferents": [] if understood else ["مرجع افتتاحیه نامشخص است"],
    }


def _hook_review(candidate, **overrides) -> dict:
    value = {
        "version": "2.0",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "strength": "acceptable",
        "rationale": "The rendered opening establishes a concrete gap immediately.",
        "observations": [
            "Opening text is readable and directional while muted.",
            "The first visible action supports the spoken contradiction.",
        ],
        "mutedHookDirectionConfirmed": True,
        "coldViewer": _cold_viewer(),
        "visualTypography": {
            "policyVersion": "1.0",
            "evidenceSource": "rendered_opening_pixels",
            "recipeId": "editorial-hero-balanced",
            "occupancyRatio": 0.31,
            "durationSeconds": 2.8,
            "hierarchyPassed": True,
            "emphasisPassed": True,
            "lineBalancePassed": True,
            "opticalPlacementPassed": True,
        },
        "visualVoiceAlignment": "acceptable",
        "actualPayoffSeconds": 4.8,
        "concretePayoffKind": "result",
        "payoffEvidence": "The concrete result reaches the viewer at 4.8 seconds.",
        "payoffBeginsPromptly": True,
    }
    value.update(overrides)
    return value




def _bind_cold_viewer_input(review: dict, candidate, project, *, extra_context: dict | None = None):
    frames = sorted(str(path) for path in (project / "artifacts" / "final-review-frames").glob("*.jpg"))[:3]
    payload = build_cold_viewer_review_input(
        candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
        opening_evidence={
            "framePaths": frames,
            "startSeconds": 0.0,
            "endSeconds": 3.0,
        },
    )
    if extra_context:
        payload.update(extra_context)
    path = project / "artifacts" / "cold_viewer_review_input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    review["metadata"]["coldViewerReviewInput"] = {"path": str(path), "sha256": digest}
    review["metadata"]["hookQualityReview"]["coldViewer"]["reviewInputSha256"] = digest
    return path

def test_current_hook_audit_requires_evidence_backed_final_hook_review(tmp_path):
    _, _, review_path, _ = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {"hookQualityAudit": _hook_audit()}
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review|visual/voice alignment"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_evidence_backed_hook_review_requires_rendered_alignment_and_prompt_payoff(tmp_path):
    _, candidate, review_path, _ = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(
            candidate,
            visualVoiceAlignment="weak",
            payoffBeginsPromptly=False,
        ),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_valid_evidence_backed_hook_review_allows_existing_final_review_contract(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate),
    }
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    state = complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=BASE,
    )
    assert state["next_phase"] == "awaiting_human"
    evidence = state["evidence"]["final_review"]
    quality_path = Path(evidence["quality_evidence_path"])
    assert quality_path.is_file()
    assert evidence["quality_evidence_sha256"] == workflow._hash_file(quality_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    assert quality["openingSummary"]["coldViewComprehension"] is True
    assert {item["provenance"]["domain"] for item in quality["evidence"]} == {
        "authored_timeline", "rendered_pixels", "semantic_review"
    }
    assert "qualityEvidence" not in evidence


def test_passing_final_review_requires_digest_bound_cold_viewer_input_artifact(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="cold-viewer review input"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_passing_final_review_rejects_cold_viewer_input_with_authoring_context(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate),
    }
    _bind_cold_viewer_input(
        review, candidate, tmp_path / "run",
        extra_context={"approvedScript": "hidden authoring context must never reach blind review"},
    )
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="unsupported authoring context"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_hook_quality_review_strength_must_match_render_report_hook_strength(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate, strength="acceptable"),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "strong"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="hook_strength"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_weak_rendered_hook_can_be_persisted_as_revision_evidence(tmp_path):
    _, candidate, review_path, _ = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["status"] = "revise"
    review["recommended_action"] = "revise_edit"
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(
            candidate,
            strength="weak",
            mutedHookDirectionConfirmed=False,
            coldViewer=_cold_viewer(understood=False),
            visualVoiceAlignment="weak",
            payoffBeginsPromptly=False,
        ),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="must pass"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_final_review_rejects_authoring_agent_self_certification(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate, reviewerRole="authoring_agent"),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="independent|hook-quality review"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_final_review_rejects_mix_intelligible_without_numeric_audio_evidence(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate),
    }
    review["checks"]["audio_spotcheck"] = {
        "narration_present": True,
        "music_present": True,
        "unexpected_silence": False,
        "clipping_detected": False,
        "mix_intelligible": True,
        "issues": [],
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="audio.*evidence|policyVersion|rendered audio"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_final_review_binds_rendered_hook_review_to_actual_candidate_digest(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(candidate, reviewedCandidateSha256="b" * 64),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="digest"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )
