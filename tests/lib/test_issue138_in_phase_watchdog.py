from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _bootstrap


def test_run_kernel_blocks_new_external_work_after_wall_budget(tmp_path: Path):
    _bootstrap(tmp_path)
    marker = tmp_path / "external-work-ran.txt"
    child = (
        "from pathlib import Path; "
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')"
    )

    with pytest.raises(kernel.PersianRunKernelError, match="wall_budget_exceeded"):
        kernel.start_phase_job(
            "run",
            job_id="late-execution",
            phase="prepare_inputs",
            argv=[sys.executable, "-c", child],
            idempotence_key="late-execution-v1",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(minutes=46),
        )

    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    stop = state["budget_stop"]
    assert state["status"] == "failed"
    assert stop["quality_disposition"] == "needs_decision"
    assert stop["reason"] == "wall_budget_exceeded"
    assert stop["boundary_before_operation"] == "run-kernel:start"
    assert stop["phase"] == "prepare_inputs"
    assert stop["phase_attempt"] is None
    assert stop["operation_evidence"]["job_id"] == "late-execution"
    assert int((state.get("attempts") or {}).get("prepare_inputs", 0)) == 0
    assert not marker.exists()
    assert not (tmp_path / "run" / ".jobs" / "idempotence.json").exists()


def test_cli_front_door_stops_before_new_work_span(tmp_path: Path, monkeypatch):
    _bootstrap(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state["budget_window_started_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=46)
    ).isoformat()
    workflow._write_state(tmp_path / "run", state)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        workflow.main([
            "work-start",
            "run",
            "--category",
            "agent_editorial_work",
            "--name",
            "late-editorial-work",
        ])
    assert exc_info.value.code == 2

    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    stop = state["budget_stop"]
    assert state["status"] == "failed"
    assert stop["reason"] == "wall_budget_exceeded"
    assert stop["quality_disposition"] == "needs_decision"
    assert stop["boundary_before_operation"] == "workflow:work-start"
    assert not any(
        span.get("kind") == "explicit_work"
        for span in (state.get("causal_telemetry") or {}).get("spans", [])
    )


def test_run_kernel_rechecks_budget_at_live_child_boundaries(monkeypatch):
    operations = []

    monkeypatch.setattr(
        kernel, "start_phase_job",
        lambda *args, **kwargs: {"executionOutcome": "pending"},
    )
    monkeypatch.setattr(
        kernel, "reconcile_phase_job",
        lambda *args, **kwargs: {"executionOutcome": "pending"},
    )
    monkeypatch.setattr(kernel.time, "sleep", lambda _seconds: None)

    def fake_budget_guard(_project_id, *, operation, **_kwargs):
        operations.append(operation)
        if operation == "run-kernel:after-reconcile":
            raise workflow.PersianVideoWorkflowError(
                "wall_budget_exceeded: simulated live-child overrun"
            )
        return {}

    monkeypatch.setattr(workflow, "enforce_front_door_budget", fake_budget_guard)

    with pytest.raises(kernel.PersianRunKernelError, match="wall_budget_exceeded"):
        kernel.run_phase_job(
            "run",
            job_id="live-child",
            phase="prepare_inputs",
            argv=["fixture"],
            idempotence_key="live-child-v1",
            poll_interval_seconds=0.001,
            timeout_seconds=1.0,
        )

    assert operations == [
        "run-kernel:after-start",
        "run-kernel:wait",
        "run-kernel:after-reconcile",
    ]


def test_asset_result_remains_available_as_external_settlement(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("asset-result must not be blocked before settlement")

    monkeypatch.setattr(workflow, "enforce_front_door_budget", fail_if_called)
    args = type("Args", (), {"command": "asset-result", "project_id": "run"})()
    workflow._enforce_cli_front_door_budget(args)
