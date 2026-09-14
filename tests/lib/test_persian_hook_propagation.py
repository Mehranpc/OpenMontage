from __future__ import annotations

import json

import pytest

import lib.persian_video_workflow as workflow
from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase
from tests.lib.test_persian_video_workflow import BASE, _review_ready_project


def _hook_audit() -> dict:
    return {
        "version": "1.0",
        "required": True,
        "platformTarget": "instagram-reels",
        "disposition": "acceptable",
        "problems": [],
        "advisories": ["opening has no evidenced post-start visual change"],
    }


def _bind_preflight_hook_audit(tmp_path, state: dict) -> None:
    project = tmp_path / "run"
    preflight_dir = project / ".preflight" / "edit" / "hook-pass"
    preflight_dir.mkdir(parents=True, exist_ok=True)
    report_path = preflight_dir / "preflight_report.json"
    report_path.write_text(
        json.dumps({"ok": True, "evidence": {"hookQualityAudit": _hook_audit()}}),
        encoding="utf-8",
    )
    evidence = dict(state.get("evidence") or {})
    evidence["no_copy_preflight"] = {"preflight_report_path": str(report_path)}
    state["evidence"] = evidence
    workflow._write_state(project, state)


def test_final_review_cannot_omit_hook_review_when_preflight_required_it(tmp_path):
    state, _, review_path, _ = _review_ready_project(tmp_path)
    _bind_preflight_hook_audit(tmp_path, state)

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review"):
        complete_phase(
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
        )


def test_final_review_hook_audit_must_match_preflight_audit(tmp_path):
    state, _, review_path, _ = _review_ready_project(tmp_path)
    _bind_preflight_hook_audit(tmp_path, state)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": {**_hook_audit(), "disposition": "strong"},
        "hookQualityReview": {
            "version": "1.0",
            "strength": "acceptable",
            "rationale": "Rendered opening remains clear and relevant.",
            "observations": ["Muted premise is clear.", "Opening visual supports the claim."],
            "mutedHookDirectionConfirmed": True,
            "visualVoiceAlignment": "acceptable",
            "payoffBeginsPromptly": True,
        },
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="does not match preflight"):
        complete_phase(
            "run",
            "final_review",
            evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path,
            now=BASE,
        )
