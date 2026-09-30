"""#348: deferred durable reporting is lag, not work that erases parked silence."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from lib.persian_workflow_telemetry import record_causal_interval
from tests.lib.test_issue342_parked_time_not_wall_budget import _setup, _commands, BASE


@pytest.mark.parametrize("active_work", [False, True])
def test_reconciled_job_lag_does_not_charge_a_parked_run(
    tmp_path: Path, monkeypatch, active_work: bool,
) -> None:
    root, _ = _setup(tmp_path)
    kernel.start_phase_job(
        "run", job_id="search", phase="prepare_inputs",
        argv=["python", "-c", "pass"], idempotence_key="search",
        telemetry_category="provider_network_wait", owns_transition=False,
        pipeline_dir=tmp_path, launch=False, now=BASE + timedelta(seconds=5),
    )
    _commands(root, ("workflow:asset-search", 0, 10),
              ("workflow:asset-candidate-stage", 7200, 7210))
    if active_work:
        state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
        record_causal_interval(
            state, span_id="work:review", name="actual continuous review",
            category="agent_editorial_work", kind="explicit_work",
            started_at=BASE + timedelta(seconds=60),
            finished_at=BASE + timedelta(seconds=7200),
            parent_span_id=state["causal_telemetry"]["run_span_id"],
            count_toward_wall=True, outcome="succeeded",
        )
        workflow._write_state(root, state)

    terminal = {
        "jobId": "search", "status": "succeeded",
        "startedAt": (BASE + timedelta(seconds=5)).isoformat(),
        "finishedAt": (BASE + timedelta(seconds=60)).isoformat(),
        "processOutcome": "succeeded", "semanticOutcome": "succeeded",
        "executionOutcome": "succeeded", "reportingOutcome": "succeeded",
        "exitCode": 0, "semanticResult": {"success": True, "data": {}},
    }
    monkeypatch.setattr(workflow, "reconcile_workflow_job", lambda *a, **kw: terminal)
    observed = BASE + timedelta(seconds=7200)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return observed

    monkeypatch.setattr(kernel, "datetime", Clock)
    reconciled = kernel.reconcile_phase_job("run", "search", pipeline_dir=tmp_path)
    assert reconciled["executionEnvelope"]["telemetryOutcome"] == "succeeded"
    assert reconciled["executionOutcome"] == "succeeded"

    now = BASE + timedelta(seconds=7220)
    if active_work:
        # Real measured review still charges the gap and exceeds the budget.
        with pytest.raises(workflow.PersianVideoWorkflowError, match="wall_budget_exceeded"):
            workflow.enforce_front_door_budget(
                "run", operation="workflow:work-start", pipeline_dir=tmp_path, now=now,
            )
        assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["budget_stop"]["parked_seconds"] == 0
    else:
        # The reporting-lag diagnostic remains visible; only the budget treats
        # the unattended interval as parked.
        status = workflow.workflow_status("run", pipeline_dir=tmp_path, now=now)
        assert status["time_accounting"]["accounting_lag_seconds"] == pytest.approx(7140)
        assert status["operational_summary"]["parked_seconds"] == pytest.approx(7140)
        assert status["operational_summary"]["charged_wall_seconds"] == pytest.approx(80)
        workflow.enforce_front_door_budget(
            "run", operation="workflow:work-start", pipeline_dir=tmp_path, now=now,
        )
        span = workflow.start_explicit_work_span(
            "run", category="agent_editorial_work", name="new active work",
            pipeline_dir=tmp_path, now=now,
        )
        assert span["kind"] == "explicit_work"
        assert not workflow.load_workflow_state("run", pipeline_dir=tmp_path).get("budget_stop")
