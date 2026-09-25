"""Issue #81 Seam 1: regression coverage for required-but-unasserted behaviors.

Three front-door behaviors named in the Seam 1 matrix had no test:

* a revision window's accounting must be distinct from the whole run's,
* an authoritative late-hook advisory still requires every other independent
  rendered check (covered in ``test_persian_hook_timing_policy.py``),
* genuinely overlapping durable jobs must be accounted once with the overlap
  reported, not double counted.

These tests drive the existing public seams and assert persisted state, not logs.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import timedelta
from pathlib import Path

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import (
    complete_phase,
    record_phase_attempt,
    request_send_back,
)
from tests.lib.test_persian_video_workflow import (
    BASE,
    _checkpoint,
    _prepare_inputs_evidence,
    _report,
    _review_ready_project,
    _write_final_review,
)


def test_revision_window_accounting_is_distinct_from_whole_run(tmp_path: Path) -> None:
    """A second revision window reports only itself; the run still reports its whole cost.

    ``performance_summary.revision_window`` is what a new cycle costs; the top-level
    ``workflow_wall_seconds`` is what the run cost overall. A new window must not
    erase the prior cost, and the two numbers must genuinely differ.
    """
    _, candidate, review_path, _ = _review_ready_project(tmp_path)

    first_stop = BASE + timedelta(minutes=3)
    state = complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=first_stop,
    )
    state = complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=first_stop)
    assert state["status"] == "awaiting_human"
    # The first window starts where the run did, so it equals the whole run.
    assert state["performance_summary"]["revision_window"]["workflow_wall_seconds"] == 180.0
    assert state["performance_summary"]["workflow_wall_seconds"] == 180.0

    # An explicit user revision opens a fresh wall-budget window. This is the
    # public send-back path that resets ``budget_window_started_at``.
    revision_at = BASE + timedelta(minutes=20)
    state = request_send_back(
        "run", "final_review", reason="user supplied new editorial feedback",
        user_directed_revision=True, pipeline_dir=tmp_path, now=revision_at,
    )
    assert state["budget_window_started_at"] == revision_at.isoformat()
    assert state["user_revision_cycles"] == 1
    assert state["next_phase"] == "final_review"

    # Re-drive the second window through the same lifecycle seam.
    review_path = _write_final_review(tmp_path / "run", candidate)
    report = _report(candidate, review_ref=str(review_path))
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    record_phase_attempt("run", "final_review", pipeline_dir=tmp_path, now=revision_at)
    state = complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=BASE + timedelta(minutes=23),
    )
    second_stop = BASE + timedelta(minutes=30)
    state = complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=second_stop)
    assert state["status"] == "awaiting_human"

    summary = state["performance_summary"]
    assert summary["revision_cycle"] == 1
    # The revision window measures only the second cycle (T2 -> T3).
    assert summary["revision_window"]["workflow_wall_seconds"] == 600.0
    # The top-level metric still measures the whole run (created -> T3).
    assert summary["workflow_wall_seconds"] == 1800.0
    assert (
        summary["revision_window"]["workflow_wall_seconds"]
        != summary["workflow_wall_seconds"]
    )
    # The prior summary is retained rather than overwritten.
    assert len(state["performance_summary_history"]) == 1
    assert state["performance_summary_history"][0]["workflow_wall_seconds"] == 180.0


# --------------------------------------------------------------------------
# Overlapping durable jobs: explicit concurrency without double counting
# --------------------------------------------------------------------------

_SLEEPING_CHILD = (
    "import json, os, time; from pathlib import Path; "
    "time.sleep(0.4); "
    "p = Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']); "
    "p.write_text(json.dumps({'success': True}))"
)


def _fresh_project(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"stable-audio-input")
    workflow.bootstrap_persian_video(
        title="seam1 gaps",
        narration_path=str(narration),
        approved_script="متن تأییدشده برای آزمون",
        project_id="run",
        pipeline_dir=projects_root,
        backlot_opener=lambda _project_id: 0,
        now=BASE,
    )
    return projects_root


def _start_job(
    projects_root: Path, job_id: str, *, phase: str = "prepare_inputs", now=None
) -> None:
    kernel.start_phase_job(
        "run",
        job_id=job_id,
        phase=phase,
        argv=[sys.executable, "-c", _SLEEPING_CHILD],
        idempotence_key=f"{job_id}-v1",
        telemetry_category="provider_network_wait",
        pipeline_dir=projects_root,
        now=now or BASE + timedelta(seconds=5),
    )


def _settle_job(projects_root: Path, job_id: str) -> dict:
    for _ in range(120):
        result = kernel.reconcile_phase_job("run", job_id, pipeline_dir=projects_root)
        if result.get("status") in {"succeeded", "failed", "interrupted"}:
            return result
        time.sleep(0.05)
    return result


def _wait_durable_terminal(projects_root: Path, job_id: str) -> None:
    """Wait for the child to finish without reconciling its causal telemetry."""
    path = projects_root / "run" / ".jobs" / job_id / "state.json"
    for _ in range(120):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("status") in {"succeeded", "failed", "interrupted"}
            and payload.get("reportingOutcome") in {"succeeded", "failed"}
        ):
            return
        time.sleep(0.05)


def _retime_job(projects_root: Path, job_id: str, started, finished) -> None:
    """Rewrite a settled durable job onto the deterministic workflow clock."""
    job_dir = projects_root / "run" / ".jobs" / job_id
    durable_path = job_dir / "state.json"
    durable = json.loads(durable_path.read_text(encoding="utf-8"))
    durable.update({
        "createdAt": started.isoformat(),
        "startedAt": started.isoformat(),
        "heartbeatAt": finished.isoformat(),
        "finishedAt": finished.isoformat(),
    })
    durable_path.write_text(json.dumps(durable, indent=2) + "\n", encoding="utf-8")

    result_path = job_dir / "result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["heartbeatAt"] = finished.isoformat()
        result["finishedAt"] = finished.isoformat()
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    envelope_path = job_dir / "execution-envelope.json"
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["startedAt"] = started.isoformat()
    envelope["telemetryOutcome"] = "pending"
    envelope.pop("telemetryError", None)
    envelope_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")


def _drop_recorded_spans(projects_root: Path, *job_ids: str) -> None:
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    prefixes = tuple(f"reconcile:{job_id}" for job_id in job_ids)
    state["causal_telemetry"]["spans"] = [
        span
        for span in state["causal_telemetry"]["spans"]
        if span.get("span_id") not in {f"job:{job_id}" for job_id in job_ids}
        and not str(span.get("span_id") or "").startswith(prefixes)
    ]
    workflow._write_state(projects_root / "run", state)


def test_overlapping_durable_jobs_are_accounted_once_with_explicit_concurrency(
    tmp_path: Path,
) -> None:
    """Two genuinely concurrent durable jobs are counted once, overlap reported.

    #81 Seam 1 requires "overlapping jobs" accounting: the union of the two job
    intervals is measured once and the overlapped seconds surface as
    ``explicit_concurrency_seconds`` rather than being double counted.
    """
    projects_root = _fresh_project(tmp_path)

    # job-b starts while job-a is still running, so the two executions genuinely
    # overlap in real time before they are retimed onto the deterministic clock.
    _start_job(projects_root, "job-a")
    _start_job(projects_root, "job-b")
    _settle_job(projects_root, "job-a")
    _settle_job(projects_root, "job-b")

    # Pin the two overlapping intervals: A=[5,13], B=[8,10], overlap=[8,10].
    # job-a finishes last so its reconciliation lag attaches after the union.
    _retime_job(
        projects_root, "job-a",
        BASE + timedelta(seconds=5), BASE + timedelta(seconds=13),
    )
    _retime_job(
        projects_root, "job-b",
        BASE + timedelta(seconds=8), BASE + timedelta(seconds=10),
    )
    _drop_recorded_spans(projects_root, "job-a", "job-b")

    kernel.reconcile_terminal_jobs("run", pipeline_dir=projects_root)

    for job_id in ("job-a", "job-b"):
        envelope = kernel.load_execution_envelope("run", job_id, pipeline_dir=projects_root)
        assert envelope["executionOutcome"] == "succeeded"
        assert envelope["telemetryOutcome"] == "succeeded", envelope.get("telemetryError")

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    job_spans = [
        span for span in state["causal_telemetry"]["spans"] if span.get("kind") == "durable_job"
    ]
    assert {span["span_id"] for span in job_spans} == {"job:job-a", "job:job-b"}
    # Both jobs declare one shared, non-empty concurrency identity, so their
    # genuine overlap is recorded rather than rejected.
    groups = {span["concurrency_group"] for span in job_spans}
    assert len(groups) == 1
    assert groups != {""}

    accounting = workflow.phase_time_accounting(
        state, now=BASE + timedelta(seconds=13)
    )
    # The union of [5,13] and [8,10] is measured exactly once (8s).
    assert accounting["causal_covered_seconds"] == 8.0
    # The overlapped [8,10] is reported as explicit concurrency, not double counted.
    assert accounting["explicit_concurrency_seconds"] == 2.0
    # Each job's raw duration is counted exactly once (8s + 2s).
    assert accounting["provider_wait_seconds"] == 10.0


def test_cross_phase_durable_jobs_reconcile_at_the_terminal_seam(tmp_path: Path) -> None:
    """Jobs left unreconciled across phases still reconcile once at the terminal seam.

    ``require_measured_phase_commit`` does not gate non-media phases, so a phase
    can advance with its durable job still unreconciled, and reconciliation is
    deferred to the terminal awaiting_human path. An earlier job's reconciliation
    lag therefore spans later phases' windows, and must share the durable-job
    concurrency identity with a later job's span rather than hard-fail.
    """
    projects_root = _fresh_project(tmp_path)

    # job-a runs in prepare_inputs and is deliberately left unreconciled.
    _start_job(projects_root, "job-a", phase="prepare_inputs")
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    complete_phase(
        "run", "prepare_inputs", evidence=_prepare_inputs_evidence(state),
        pipeline_dir=projects_root, now=BASE + timedelta(seconds=6),
    )
    assert (
        workflow.load_workflow_state("run", pipeline_dir=projects_root)["next_phase"]
        == "align_script_timing"
    )

    # job-b runs in the next phase, still before job-a is reconciled.
    _start_job(
        projects_root, "job-b", phase="align_script_timing",
        now=BASE + timedelta(seconds=11),
    )
    _wait_durable_terminal(projects_root, "job-a")
    _wait_durable_terminal(projects_root, "job-b")

    # Non-overlapping execution: A=[5,10], B=[12,16]. The collision is between
    # job-a's reconciliation lag and job-b's span, not the executions themselves.
    _retime_job(
        projects_root, "job-a",
        BASE + timedelta(seconds=5), BASE + timedelta(seconds=10),
    )
    _retime_job(
        projects_root, "job-b",
        BASE + timedelta(seconds=12), BASE + timedelta(seconds=16),
    )
    _drop_recorded_spans(projects_root, "job-a", "job-b")

    # Terminal reconciliation must succeed instead of failing the later job.
    kernel.reconcile_terminal_jobs("run", pipeline_dir=projects_root)

    for job_id, phase in (("job-a", "prepare_inputs"), ("job-b", "align_script_timing")):
        envelope = kernel.load_execution_envelope("run", job_id, pipeline_dir=projects_root)
        assert envelope["phase"] == phase
        assert envelope["executionOutcome"] == "succeeded"
        assert envelope["telemetryOutcome"] == "succeeded", envelope.get("telemetryError")

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(
        state, now=BASE + timedelta(seconds=16)
    )
    # Every counted interval is attributed once: the union of [5,10], [12,16] and
    # job-a's [10,16]-clipped reconciliation lag is [5,16] == 11s.
    assert accounting["causal_covered_seconds"] == 11.0
    # Each job's execution time is counted once (5s + 4s).
    assert accounting["provider_wait_seconds"] == 9.0
    # The cross-phase overlap is still surfaced rather than double counted.
    assert accounting["explicit_concurrency_seconds"] > 0.0
