"""#360: preparation is bound to its inputs, and diagnosis stays possible at a stop.

A readiness snapshot is not authorisation: a mutation prepared against changed inputs
refuses without writing. At a genuine budget stop, status still reports readiness,
the blocker set and the decision actually required, while active work stays refused.
Stop evidence is shown apart from live work spans, so an old open-span ID is not read
as a current accounting defect.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_assets
from lib import persian_video_workflow as workflow
from lib.persian_asset_workspace import AssetAdmissionRefused
from tests.lib.test_issue224_plan_reconcile import _run_at_acquire
from tests.lib.test_issue360_truthful_readiness import BASE, _candidate, _project_bytes

EVENTS = ("event-0", "event-1", "event-2")


def _readiness(tmp_path: Path) -> str:
    status = workflow.workflow_status("run", pipeline_dir=tmp_path, now=BASE)
    return status["acquisition"]["readiness"]["inputsSha256"]


def _select(tmp_path: Path, event: str, candidate: str, **kwargs):
    return workflow.select_workflow_asset_candidate(
        "run", event, candidate, rejected_alternatives=kwargs.pop("rejected", {}),
        pipeline_dir=tmp_path, **kwargs,
    )


def _change_plan(tmp_path: Path) -> None:
    workflow.reconcile_scene_plan(
        "run", [{"visual_event_id": "event-2", "set": {"negative_space": "centre_band"}}],
        reason="dependency change", pipeline_dir=tmp_path, now=BASE,
    )


def _change_selection(tmp_path: Path) -> None:
    _select(tmp_path, "event-2", _candidate(tmp_path, "event-2", "other-event"))


def _change_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(persian_assets, "ASSET_ADMISSION_POLICY_VERSION", "360.test")


def _change_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace, "_implementation_sha", lambda: "f" * 40)


@pytest.mark.parametrize("dependency", ["plan", "selection", "policy", "implementation"])
@pytest.mark.parametrize("mutation", ["select", "replace", "idempotent", "reject"])
def test_a_stale_preparation_refuses_every_mutation_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dependency: str, mutation: str,
) -> None:
    project = _run_at_acquire(tmp_path)
    first = _candidate(tmp_path, "event-0", "first")
    _select(tmp_path, "event-0", first)
    second = _candidate(tmp_path, "event-0", "second")
    fresh = _candidate(tmp_path, "event-1", "fresh")
    prepared = _readiness(tmp_path)
    {
        "plan": lambda: _change_plan(tmp_path),
        "selection": lambda: _change_selection(tmp_path),
        "policy": lambda: _change_policy(monkeypatch),
        "implementation": lambda: _change_code(monkeypatch),
    }[dependency]()
    before = _project_bytes(project)
    attempt = {
        "select": lambda sha: _select(tmp_path, "event-1", fresh, expected_readiness_sha256=sha),
        "replace": lambda sha: _select(tmp_path, "event-0", second, replace_existing=True,
                                       rejected={first: "prefer second"}, expected_readiness_sha256=sha),
        "idempotent": lambda sha: _select(tmp_path, "event-0", first,
                                          rejected={second: "keep first"}, expected_readiness_sha256=sha),
        "reject": lambda sha: workflow.reject_workflow_asset_candidate(
            "run", second, category="editorial", reason="not needed", pipeline_dir=tmp_path,
            expected_readiness_sha256=sha),
    }[mutation]

    with pytest.raises(AssetAdmissionRefused) as refused:
        attempt(prepared)
    assert _project_bytes(project) == before
    [diagnostic] = refused.value.diagnostics
    assert diagnostic["code"] == "STALE_PREPARATION"
    assert diagnostic["expected"] == prepared and diagnostic["observed"] != prepared

    attempt(_readiness(tmp_path))  # a refreshed snapshot is accepted


def _stopped_run(tmp_path: Path) -> tuple[Path, str]:
    project = _run_at_acquire(tmp_path)
    bad = _candidate(tmp_path, "event-0", "bad", shows_subject=False)
    from tests.lib.test_issue360_truthful_readiness import _legacy_select

    _legacy_select(project, "event-0", bad)
    span = workflow.start_explicit_work_span(
        "run", category="agent_editorial_work", name="choose footage", pipeline_dir=tmp_path, now=BASE,
    )
    with pytest.raises(workflow.PersianVideoWorkflowError, match="wall_budget_exceeded"):
        workflow.enforce_front_door_budget(
            "run", operation="workflow:asset-candidate-select", pipeline_dir=tmp_path,
            now=BASE + timedelta(days=1),
        )
    return project, span["span_id"]


def test_status_diagnoses_a_genuine_stop_without_granting_or_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    project, _ = _stopped_run(tmp_path)
    before = _project_bytes(project)
    later = BASE + timedelta(days=1, minutes=5)
    status = workflow.workflow_status("run", pipeline_dir=tmp_path, now=later)
    again = workflow.workflow_status("run", pipeline_dir=tmp_path, now=later)
    assert _project_bytes(project) == before

    preparation = status["acquisition"]["preparation"]
    assert preparation["blockers"] == {"event-0": ["SUBJECT_CONTINUITY_LOST"]}
    assert preparation["decisionRequired"]["kind"] == "budget_stop"
    assert preparation["decisionRequired"]["operation"] == "workflow:asset-candidate-select"
    assert preparation["remainingRetryPasses"] == [0, 1]
    assert status["diagnostic_elapsed_seconds"] >= 0
    # Diagnosis time is reported beside, not subtracted from, the run's clocks.
    for key in ("total_elapsed_seconds", "charged_wall_seconds", "parked_seconds"):
        assert status["operational_summary"][key] == again["operational_summary"][key]

    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    with pytest.raises(SystemExit) as exited:
        workflow.main(["asset-candidate-select", "run", "event-1", "anything"])
    assert exited.value.code == 2
    # The persisted stop leaves the run inactive, so active work stays refused.
    assert "only during active acquire_assets" in capsys.readouterr().err
    assert workflow.main(["status", "run"]) == 0
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["budget_stop"]


def test_a_stop_snapshot_is_not_live_work_and_finishing_twice_is_idempotent(tmp_path: Path) -> None:
    project, span_id = _stopped_run(tmp_path)
    view = workflow.workflow_status("run", pipeline_dir=tmp_path, now=BASE)["work_spans"]
    assert view["live_open_span_ids"] == [span_id]
    assert view["stop_snapshot_open_span_ids"] == [span_id]
    assert view["stop_snapshot_still_open"] == [span_id]

    ended = BASE + timedelta(minutes=20)
    finished = workflow.finish_explicit_work_span("run", span_id, pipeline_dir=tmp_path, now=ended)
    assert finished["outcome"] == "succeeded" and finished["count_toward_wall"] is True
    state_bytes = (project / "workflow_state.json").read_bytes() if (project / "workflow_state.json").is_file() else None
    assert workflow.finish_explicit_work_span(
        "run", span_id, pipeline_dir=tmp_path, now=ended + timedelta(hours=1),
    ) == finished
    if state_bytes is not None:
        assert (project / "workflow_state.json").read_bytes() == state_bytes

    view = workflow.workflow_status("run", pipeline_dir=tmp_path, now=ended)["work_spans"]
    assert view["live_open_span_ids"] == []
    assert view["stop_snapshot_open_span_ids"] == [span_id]  # historical evidence stays
    assert view["stop_snapshot_since_finished"][span_id]["outcome"] == "succeeded"
    assert view["stop_snapshot_still_open"] == []
    assert json.loads(json.dumps(view)) == view
