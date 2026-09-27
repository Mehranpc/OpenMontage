"""#224: correcting the plan against reviewed footage does not spend a send-back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_assets
from lib import persian_video_workflow as workflow
from lib.checkpoint import read_checkpoint
from lib.persian_video_workflow import (
    complete_phase, load_workflow_state, reconcile_scene_plan, record_phase_attempt,
)
from tests.lib.test_issue195_scene_plan_duration_gate import (
    BASE, _advance_to_plan_scenes, _bootstrap, _write_checkpoint,
)
from tests.lib.test_issue213_plan_time_moment_feasibility import _beats
from tests.contracts.test_phase0_contracts import sample_artifact


def _run_at_acquire(tmp_path: Path) -> Path:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    # Real runs have completed idea/script checkpoints by now; writing scene_plan needs them.
    for stage, artifact in (("idea", "brief"), ("script", "script")):
        _write_checkpoint(tmp_path, stage, artifact, sample_artifact(artifact))
    plan = {"version": "2.0", "format": "vertical", "subject": "phone",
            "beats": _beats((4.0, None), (4.0, None), (52.0, None))}
    _write_checkpoint(tmp_path, "scene_plan", "scene_plan", plan)
    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    complete_phase("run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE)
    assert load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "acquire_assets"
    return tmp_path / "run"


def _plan(tmp_path: Path) -> dict:
    return read_checkpoint(tmp_path, "run", "scene_plan")["artifacts"]["scene_plan"]


def _event(plan: dict, event_id: str) -> dict:
    return next(e for b in plan["beats"] for e in b["visual_events"] if e["id"] == event_id)


def test_reconcile_corrects_declarations_without_spending_a_send_back(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    result = reconcile_scene_plan(
        "run",
        [{"visual_event_id": "event-0", "set": {"shows_subject": False, "carries_moment": False}},
         {"visual_event_id": "event-1", "set": {"negative_space": "centre_band"}}],
        reason="footage has no phone in event-0; event-1 is clear in the centre",
        pipeline_dir=tmp_path, now=BASE,
    )
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert result["outcome"] == "plan_reconciled"
    assert state["send_backs"] == 0 and result["sendBacksUsed"] == 0
    assert state["next_phase"] == "acquire_assets"
    plan = _plan(tmp_path)
    assert _event(plan, "event-0")["shows_subject"] is False
    assert _event(plan, "event-0")["carries_moment"] is False
    assert _event(plan, "event-1")["negative_space"] == "centre_band"
    # Timing and queries untouched.
    assert _event(plan, "event-1")["duration_seconds"] == 4.0
    assert _event(plan, "event-1")["queries"][0] == "phone on plain table wide shot"
    record = read_checkpoint(tmp_path, "run", "scene_plan")["metadata"]["plan_reconciliations"]
    assert record[-1]["amendments"][0]["before"] == {"shows_subject": True, "carries_moment": True}


def test_timing_queries_and_identity_are_refused(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    for field in ("duration_seconds", "queries", "id"):
        with pytest.raises(workflow.PersianVideoWorkflowError, match="cannot be reconciled"):
            reconcile_scene_plan(
                "run", [{"visual_event_id": "event-0", "set": {field: 1}}],
                reason="x", pipeline_dir=tmp_path, now=BASE,
            )


def test_a_carrier_must_keep_a_legal_region(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="negative_space"):
        reconcile_scene_plan(
            "run", [{"visual_event_id": "event-0", "set": {"negative_space": None}}],
            reason="x", pipeline_dir=tmp_path, now=BASE,
        )


def test_infeasible_copy_is_refused_like_at_plan_time(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    long_copy = [{"role": "hero", "text": "این یک جملهٔ خیلی طولانی است که در چهار ثانیه خوانده نمی‌شود اصلاً"}]
    with pytest.raises(workflow.PersianVideoWorkflowError, match="MOMENT_COPY_INFEASIBLE"):
        reconcile_scene_plan(
            "run", [{"visual_event_id": "event-0", "set": {"moment_copy": long_copy}}],
            reason="x", pipeline_dir=tmp_path, now=BASE,
        )


def test_budget_is_bounded_per_window_and_reset_by_user_revision(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    limit = load_workflow_state("run", pipeline_dir=tmp_path)["budgets"]["max_revisions_per_stage"]
    for _ in range(limit):
        reconcile_scene_plan("run", [{"visual_event_id": "event-2", "set": {"shows_subject": True}}],
                             reason="x", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="reconciliation budget exhausted"):
        reconcile_scene_plan("run", [{"visual_event_id": "event-2", "set": {"shows_subject": True}}],
                             reason="x", pipeline_dir=tmp_path, now=BASE)


def test_a_manifest_that_no_longer_matches_returns_to_acquire_without_a_send_back(
    tmp_path: Path, monkeypatch,
) -> None:
    root = _run_at_acquire(tmp_path)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    state["next_phase"] = "review_subject_regions"
    state["completed_phases"] = list(state["completed_phases"]) + ["acquire_assets"]
    state["asset_usage"] = {"completed_passes": [{"pass": 0}], "acquisition_cycle": 0}
    workflow._write_state(root, state)
    (root / "checkpoint_assets.json").write_text(json.dumps({
        "version": "1.0", "project_id": "run", "pipeline_type": "persian-footage",
        "stage": "assets", "status": "completed", "timestamp": BASE.isoformat(),
        "checkpoint_policy": "guided", "human_approval_required": False, "human_approved": False,
        "artifacts": {"asset_manifest": {"version": "1.0", "assets": []}},
    }), encoding="utf-8")
    monkeypatch.setattr(persian_assets, "audit_asset_manifest",
                        lambda manifest, plan=None: ["event-1: placement_space differs"])

    result = reconcile_scene_plan(
        "run", [{"visual_event_id": "event-1", "set": {"negative_space": "centre_band"}}],
        reason="carrier re-declared against reviewed footage", pipeline_dir=tmp_path, now=BASE,
    )
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert result["outcome"] == "plan_reconciled_rebuild_manifest"
    assert state["next_phase"] == "acquire_assets"
    assert state["send_backs"] == 0
    assert state["asset_usage"]["completed_passes"] == [{"pass": 0}], "acquisition state kept"
    assert not (root / "checkpoint_assets.json").exists()
    assert result["archivedCheckpoints"]


def test_a_manifest_that_still_matches_keeps_the_run_where_it_was(tmp_path: Path, monkeypatch) -> None:
    root = _run_at_acquire(tmp_path)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    state["next_phase"] = "review_subject_regions"
    workflow._write_state(root, state)
    (root / "checkpoint_assets.json").write_text(json.dumps({
        "version": "1.0", "project_id": "run", "pipeline_type": "persian-footage",
        "stage": "assets", "status": "completed", "timestamp": BASE.isoformat(),
        "checkpoint_policy": "guided", "human_approval_required": False, "human_approved": False,
        "artifacts": {"asset_manifest": {"version": "1.0", "assets": []}},
    }), encoding="utf-8")
    monkeypatch.setattr(persian_assets, "audit_asset_manifest", lambda manifest, plan=None: [])
    result = reconcile_scene_plan(
        "run", [{"visual_event_id": "event-0", "set": {"carries_moment": False}}],
        reason="move carrier off event-0", pipeline_dir=tmp_path, now=BASE,
    )
    assert result["outcome"] == "plan_reconciled"
    assert load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "review_subject_regions"
    assert (root / "checkpoint_assets.json").exists()


def test_refused_outside_the_footage_review_phases(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="reconcile-plan is for"):
        reconcile_scene_plan("run", [{"visual_event_id": "x", "set": {"shows_subject": True}}],
                             reason="x", pipeline_dir=tmp_path, now=BASE)


def test_the_region_gate_points_at_reconcile_plan() -> None:
    import inspect
    assert "reconcile-plan" in inspect.getsource(workflow._refuse_declared_negative_space_collisions)
