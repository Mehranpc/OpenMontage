from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import time

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry


BASE = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)


def _fresh_project(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"stable-audio-input")
    workflow.bootstrap_persian_video(
        title="historical reconciliation overlap",
        narration_path=str(narration),
        approved_script="متن تأییدشده برای آزمون",
        project_id="run",
        pipeline_dir=projects_root,
        backlot_opener=lambda _project_id: 0,
        now=BASE,
    )
    return projects_root


def _wait_for_terminal_durable_state(path: Path) -> dict:
    for _ in range(100):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") in {"succeeded", "failed", "interrupted"}:
            return payload
        time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


def test_historical_reconciliation_does_not_overlap_later_measured_work(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="old-failure",
        phase="prepare_inputs",
        argv=["python", "-c", "raise SystemExit(1)"],
        idempotence_key="old-failure-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )

    job_dir = projects_root / "run" / ".jobs" / "old-failure"
    durable_path = job_dir / "state.json"
    durable = _wait_for_terminal_durable_state(durable_path)
    assert durable["status"] == "failed"

    historical_start = BASE + timedelta(seconds=5)
    historical_finish = BASE + timedelta(seconds=10)
    durable.update(
        {
            "createdAt": historical_start.isoformat(),
            "startedAt": historical_start.isoformat(),
            "heartbeatAt": historical_finish.isoformat(),
            "finishedAt": historical_finish.isoformat(),
        }
    )
    durable_path.write_text(json.dumps(durable, indent=2) + "\n", encoding="utf-8")

    result_path = job_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["heartbeatAt"] = historical_finish.isoformat()
    result["finishedAt"] = historical_finish.isoformat()
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    envelope_path = job_dir / "execution-envelope.json"
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["startedAt"] = historical_start.isoformat()
    envelope["telemetryOutcome"] = "pending"
    envelope.pop("telemetryError", None)
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    trace = state["causal_telemetry"]
    trace["spans"] = [
        span for span in trace["spans"] if span.get("span_id") != "job:old-failure"
    ]
    telemetry.record_causal_interval(
        state,
        span_id="job:later-render",
        name="later measured render",
        category="browser_render_execution",
        started_at=BASE + timedelta(seconds=20),
        finished_at=BASE + timedelta(seconds=30),
        outcome="succeeded",
        kind="durable_job",
        fields={"job_id": "later-render", "phase": "render_opening_candidate", "attempt": 1},
    )
    workflow._write_state(projects_root / "run", state)

    kernel.reconcile_terminal_jobs("run", pipeline_dir=projects_root)

    reconciled = kernel.load_execution_envelope(
        "run", "old-failure", pipeline_dir=projects_root
    )
    assert reconciled["executionOutcome"] == "failed"
    assert reconciled["telemetryOutcome"] == "succeeded"

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    reconciliation = [
        span
        for span in state["causal_telemetry"]["spans"]
        if str(span.get("span_id") or "").startswith("reconcile:old-failure")
    ]
    assert len(reconciliation) >= 2
    later_start = BASE + timedelta(seconds=20)
    later_finish = BASE + timedelta(seconds=30)
    for span in reconciliation:
        start = datetime.fromisoformat(span["started_at"])
        finish = datetime.fromisoformat(span["finished_at"])
        assert finish <= later_start or start >= later_finish

    accounting = workflow.phase_time_accounting(
        state, now=BASE + timedelta(seconds=40)
    )
    assert accounting["machine_execution_seconds"] == 5.0
    assert accounting["browser_render_seconds"] == 10.0
    assert accounting["accounting_lag_seconds"] == 20.0
    assert accounting["causal_covered_seconds"] == 35.0
