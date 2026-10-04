"""#387: the v3 pipeline agent's own hook review must also pass the final_review artifact contract.

PR #400 let the durable workflow accept ``reviewerRole: pipeline_agent`` under v3,
but the artifact-contract (shape) layer still demanded an outside reviewer, so a
real v3 run was refused at final_review. The shape layer cannot see the profile;
it accepts an honestly disclosed self-review, and the durable workflow keeps
deciding whether self-review is allowed (v3 only).
"""

from __future__ import annotations

import json

import pytest
from jsonschema import ValidationError

from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase
from schemas.artifacts import validate_artifact
from tests.lib.test_persian_hook_final_review import _bind_cold_viewer_input, _hook_audit, _hook_review
from tests.lib.test_persian_video_workflow import BASE, _checkpoint, _review_ready_project


def _self_reviewed(tmp_path, *, isolated=False, role="pipeline_agent"):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    hook = _hook_review(candidate, reviewerRole=role)
    hook["coldViewer"]["contextIsolated"] = isolated
    review["metadata"] = {"hookQualityAudit": _hook_audit(), "hookQualityReview": hook}
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    return review, review_path


def test_artifact_contract_accepts_a_disclosed_pipeline_agent_review(tmp_path):
    review, _ = _self_reviewed(tmp_path)
    validate_artifact("final_review", review)


def test_pipeline_agent_cannot_claim_context_isolation(tmp_path):
    review, _ = _self_reviewed(tmp_path, isolated=True)
    with pytest.raises(ValidationError, match="cannot claim"):
        validate_artifact("final_review", review)


def test_unknown_reviewer_role_is_still_refused(tmp_path):
    review, _ = _self_reviewed(tmp_path, role="someone")
    with pytest.raises(ValidationError, match="independent reviewer"):
        validate_artifact("final_review", review)


def test_v2_workflow_still_refuses_a_self_review(tmp_path):
    _, review_path = _self_reviewed(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="independent reviewer"):
        complete_phase("run", "final_review", evidence={"final_review_path": str(review_path)},
                       pipeline_dir=tmp_path, now=BASE)
