from __future__ import annotations

import hashlib
import json

import pytest

from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase
from tests.lib.test_persian_video_workflow import BASE, _checkpoint, _review_ready_project


def _hook_audit() -> dict:
    return {
        "version": "1.0",
        "disposition": "acceptable",
        "problems": [],
        "advisories": [],
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
        "visualVoiceAlignment": "acceptable",
        "actualPayoffSeconds": 4.8,
        "concretePayoffKind": "result",
        "payoffEvidence": "The concrete result reaches the viewer at 4.8 seconds.",
        "payoffBeginsPromptly": True,
    }
    value.update(overrides)
    return value


def test_current_hook_audit_requires_evidence_backed_final_hook_review(tmp_path):
    _, _, review_path, _ = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {"hookQualityAudit": _hook_audit()}
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review"):
        complete_phase(
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
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
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
        )


def test_valid_evidence_backed_hook_review_allows_existing_final_review_contract(tmp_path):
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

    state = complete_phase(
        "run",
        "final_review",
        evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path,
        now=BASE,
    )
    assert state["next_phase"] == "awaiting_human"


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
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
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
            visualVoiceAlignment="weak",
            payoffBeginsPromptly=False,
        ),
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="must pass"):
        complete_phase(
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
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
