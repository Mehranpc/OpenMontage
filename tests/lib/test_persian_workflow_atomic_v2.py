from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.persian_video_workflow as workflow
from lib.persian_video_workflow import (
    PersianVideoWorkflowError,
    complete_phase,
    load_workflow_state,
    reconcile_workflow_state,
    record_phase_attempt,
)
from tests.lib.test_persian_video_workflow import (
    BASE,
    _advance_to,
    _bootstrap,
    _checkpoint,
    _prepare_inputs_evidence,
    _report,
)


def _assume_valid_prerequisite_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    original = workflow.read_checkpoint

    def fake_read(projects_root, project_id, stage):
        if stage in {"script", "scene_plan", "assets", "edit"}:
            return {"status": "completed", "stage": stage, "project_id": project_id}
        return original(projects_root, project_id, stage)

    monkeypatch.setattr(workflow, "read_checkpoint", fake_read)


def test_checkpoint_backed_phase_cannot_advance_state_before_checkpoint(tmp_path: Path) -> None:
    state, _ = _bootstrap(tmp_path)
    state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    state = complete_phase(
        "run",
        "prepare_inputs",
        evidence=_prepare_inputs_evidence(state),
        pipeline_dir=tmp_path,
        now=BASE,
    )
    state = record_phase_attempt("run", "align_script_timing", pipeline_dir=tmp_path, now=BASE)

    with pytest.raises(PersianVideoWorkflowError, match="checkpoint_script"):
        complete_phase("run", "align_script_timing", pipeline_dir=tmp_path, now=BASE)

    persisted = load_workflow_state("run", pipeline_dir=tmp_path)
    assert persisted["next_phase"] == "align_script_timing"
    assert "align_script_timing" not in persisted["completed_phases"]


def test_mp4_file_alone_never_fast_forwards_render_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(tmp_path)
    _assume_valid_prerequisite_checkpoints(monkeypatch)
    _advance_to(tmp_path, "render_final_candidate")
    candidate = tmp_path / "run" / "renders" / "candidate.mp4"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"render exists but lifecycle is incomplete")

    reconciled = reconcile_workflow_state("run", pipeline_dir=tmp_path)

    assert reconciled["next_phase"] == "render_final_candidate"
    assert "render_final_candidate" not in reconciled["completed_phases"]
    assert reconciled["status"] == "active"


def test_valid_digest_bound_compose_checkpoint_recovers_render_without_presentation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(tmp_path)
    _assume_valid_prerequisite_checkpoints(monkeypatch)
    _advance_to(tmp_path, "render_final_candidate")
    project = tmp_path / "run"
    candidate = project / "renders" / "candidate.mp4"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"valid rendered bytes")
    report = _report(candidate)
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    reconciled = reconcile_workflow_state("run", pipeline_dir=tmp_path)

    assert reconciled["next_phase"] == "final_review"
    assert "render_final_candidate" in reconciled["completed_phases"]
    assert reconciled["status"] == "active"
    recovery = reconciled["last_reconciliation"]["recoveredPhases"]
    assert recovery and recovery[-1]["phase"] == "render_final_candidate"
    assert recovery[-1]["candidateSha256"] == report["outputs"][0]["sha256"]


def test_digest_mismatch_refuses_recovery_fast_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap(tmp_path)
    _assume_valid_prerequisite_checkpoints(monkeypatch)
    _advance_to(tmp_path, "render_final_candidate")
    project = tmp_path / "run"
    candidate = project / "renders" / "candidate.mp4"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"real bytes")
    report = _report(candidate, digest="0" * 64)
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    reconciled = reconcile_workflow_state("run", pipeline_dir=tmp_path)

    assert reconciled["next_phase"] == "render_final_candidate"
    assert "render_final_candidate" not in reconciled["completed_phases"]
    assert any(
        item.get("phase") == "render_final_candidate"
        for item in reconciled["last_reconciliation"]["problems"]
    )
