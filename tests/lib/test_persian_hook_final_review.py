from __future__ import annotations

import json

import pytest

from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase
from tests.lib.test_persian_video_workflow import BASE, _checkpoint, _review_ready_project


def test_current_hook_audit_requires_evidence_backed_final_hook_review(tmp_path):
    _, _, review_path, report = _review_ready_project(tmp_path)
    report["metadata"] = {
        "hookQualityAudit": {
            "version": "1.0",
            "disposition": "acceptable",
            "problems": [],
            "advisories": [],
        }
    }
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review"):
        complete_phase(
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
        )


def test_evidence_backed_hook_review_must_match_reported_strength(tmp_path):
    _, _, review_path, report = _review_ready_project(tmp_path)
    report["metadata"] = {
        "hookQualityAudit": {
            "version": "1.0",
            "disposition": "acceptable",
            "problems": [],
            "advisories": [],
        },
        "hookQualityReview": {
            "version": "1.0",
            "strength": "acceptable",
            "rationale": "The rendered opening establishes a concrete gap immediately.",
            "observations": [
                "Opening text is readable muted.",
                "The first visual action supports the spoken contradiction.",
            ],
            "mutedHookDirectionConfirmed": True,
            "visualVoiceAlignment": "acceptable",
            "payoffBeginsPromptly": True,
        },
    }
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
