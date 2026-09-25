from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import time

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry

BASE = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)


def _fresh_project(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"stable-audio-input")
    workflow.bootstrap_persian_video(
        title="causal telemetry",
        narration_path=str(narration),
        approved_script="متن تأییدشده برای آزمون",
        project_id="run",
        pipeline_dir=projects_root,
        backlot_opener=lambda _project_id: 0,
        now=BASE,
    )
    return projects_root


def _semantic_child() -> str:
    return (
        "import json, os; from pathlib import Path; "
        "p=Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']); "
        "p.write_text(json.dumps({'success': True}))"
    )


def _wait(projects_root: Path, job_id: str) -> dict:
    result = kernel.reconcile_phase_job("run", job_id, pipeline_dir=projects_root)
    for _ in range(100):
        if result.get("status") in {"succeeded", "failed", "interrupted"}:
            return result
        time.sleep(0.05)
        result = kernel.reconcile_phase_job("run", job_id, pipeline_dir=projects_root)
    return result


def test_phase_attempts_join_one_persistent_production_trace(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    initial = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    trace = initial["causal_telemetry"]
    assert trace["version"] == 1
    assert trace["trace_id"]
    assert trace["run_span_id"]

    started = workflow.record_phase_attempt(
        "run", "prepare_inputs", pipeline_dir=projects_root, now=BASE + timedelta(seconds=5)
    )
    phase_spans = [
        span for span in started["causal_telemetry"]["spans"]
        if span.get("kind") == "phase_attempt" and span.get("phase") == "prepare_inputs"
    ]
    assert len(phase_spans) == 1
    assert phase_spans[0]["parent_span_id"] == trace["run_span_id"]
    assert phase_spans[0]["attempt"] == 1
    assert phase_spans[0]["category"] == "agent_editorial_work"
    assert phase_spans[0]["count_toward_wall"] is False


def test_completed_phase_does_not_certify_unobserved_work(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.record_phase_attempt(
        "run", "prepare_inputs", pipeline_dir=projects_root, now=BASE
    )
    completed = workflow.complete_phase(
        "run", "prepare_inputs", pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=100),
        evidence={
            "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
            "narration_sha256": state["input"]["narration"]["sha256"],
        },
    )
    result = workflow.phase_time_accounting(completed, now=BASE + timedelta(seconds=100))
    assert result["workflow_wall_seconds"] == 100.0
    assert result["causal_covered_seconds"] == 0.0
    assert result["unattributed_wall_seconds"] == 100.0
    assert result["editorial_wall_seconds"] == 0.0


def test_historical_residuals_remain_readable_without_blocking_measured_evidence() -> None:
    state = {"created_at": BASE.isoformat(),
             "causal_telemetry": telemetry.new_causal_trace("legacy", started_at=BASE)}
    telemetry.record_causal_interval(
        state, span_id="old-residual", name="inferred editorial work",
        category="agent_editorial_work", kind="phase_residual",
        started_at=BASE, finished_at=BASE + timedelta(seconds=100),
    )
    telemetry.record_causal_interval(
        state, span_id="measured", name="actual renderer",
        category="browser_render_execution",
        started_at=BASE + timedelta(seconds=20), finished_at=BASE + timedelta(seconds=30),
    )
    result = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=100))
    assert result["causal_coverage_percent"] == 10.0
    assert result["unattributed_wall_seconds"] == 90.0
    assert state["causal_telemetry"]["spans"][1]["count_toward_wall"] is True


def test_durable_job_records_child_span_with_explicit_semantic_category(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    started = kernel.start_phase_job(
        "run",
        job_id="provider-job",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="provider-job-v1",
        telemetry_category="provider_network_wait",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    assert started["phaseAttempt"] == 1
    final = _wait(projects_root, "provider-job")
    assert final["executionOutcome"] == "succeeded"

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    spans = state["causal_telemetry"]["spans"]
    phase_span = next(span for span in spans if span.get("kind") == "phase_attempt")
    job_span = next(span for span in spans if span.get("kind") == "durable_job")
    envelope = final["executionEnvelope"]
    assert envelope["traceId"] == state["causal_telemetry"]["trace_id"]
    assert envelope["causalSpanId"] == job_span["span_id"]
    assert envelope["parentSpanId"] == phase_span["span_id"]
    assert job_span["parent_span_id"] == phase_span["span_id"]
    assert job_span["category"] == "provider_network_wait"
    assert job_span["finished_at"]
    assert job_span["outcome"] == "succeeded"
    assert job_span["count_toward_wall"] is True


def test_causal_accounting_conserves_wall_clock_and_exposes_unattributed_time() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-1", started_at=BASE),
    }
    telemetry.record_causal_interval(
        state,
        span_id="provider",
        name="asset provider wait",
        category="provider_network_wait",
        started_at=BASE + timedelta(seconds=10),
        finished_at=BASE + timedelta(seconds=30),
    )
    telemetry.record_causal_interval(
        state,
        span_id="render",
        name="browser render",
        category="browser_render_execution",
        started_at=BASE + timedelta(seconds=40),
        finished_at=BASE + timedelta(seconds=70),
    )

    result = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=100))
    assert result["workflow_wall_seconds"] == 100.0
    assert result["causal_covered_seconds"] == 50.0
    assert result["unattributed_wall_seconds"] == 50.0
    assert result["provider_wait_seconds"] == 20.0
    assert result["browser_render_seconds"] == 30.0
    assert result["telemetry_span_count"] == 2
    assert result["causal_coverage_percent"] == 50.0


def test_overlapping_accounting_spans_require_explicit_concurrency() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-1", started_at=BASE),
    }
    telemetry.record_causal_interval(
        state,
        span_id="one",
        name="first",
        category="machine_local_execution",
        started_at=BASE,
        finished_at=BASE + timedelta(seconds=10),
    )
    with pytest.raises(ValueError, match="overlap"):
        telemetry.record_causal_interval(
            state,
            span_id="two",
            name="second",
            category="review_evidence_assembly",
            started_at=BASE + timedelta(seconds=5),
            finished_at=BASE + timedelta(seconds=15),
        )

    concurrent = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-2", started_at=BASE),
    }
    for span_id, category in (("one", "machine_local_execution"), ("two", "provider_network_wait")):
        telemetry.record_causal_interval(
            concurrent,
            span_id=span_id,
            name=span_id,
            category=category,
            started_at=BASE,
            finished_at=BASE + timedelta(seconds=10),
            concurrency_group="parallel-1",
        )
    result = workflow.phase_time_accounting(concurrent, now=BASE + timedelta(seconds=10))
    assert result["causal_covered_seconds"] == 10.0
    assert result["explicit_concurrency_seconds"] == 10.0
    assert result["unattributed_wall_seconds"] == 0.0
    assert result["causal_coverage_percent"] == 100.0


def test_terminal_job_records_reconciliation_lag_separately(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="lag-job",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="lag-job-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    final = _wait(projects_root, "lag-job")
    assert final["executionOutcome"] == "succeeded"

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    spans = state["causal_telemetry"]["spans"]
    job_span = next(span for span in spans if span.get("span_id") == "job:lag-job")
    lag_span = next(span for span in spans if span.get("span_id") == "reconcile:lag-job")
    assert lag_span["category"] == "accounting_reconciliation"
    assert lag_span["parent_span_id"] == job_span["parent_span_id"]
    assert lag_span["started_at"] == job_span["finished_at"]
    assert lag_span["finished_at"] >= lag_span["started_at"]


def test_workflow_status_surfaces_causal_trace_identity(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    status = workflow.workflow_status("run", pipeline_dir=projects_root)
    assert status["causal_trace_id"] == state["causal_telemetry"]["trace_id"]


def test_causal_span_identity_and_parentage_are_guarded() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-guard", started_at=BASE),
    }
    with pytest.raises(ValueError, match="parent span"):
        telemetry.record_causal_interval(
            state,
            span_id="orphan",
            name="orphan",
            category="machine_local_execution",
            started_at=BASE,
            finished_at=BASE + timedelta(seconds=1),
            parent_span_id="missing-parent",
        )
    with pytest.raises(ValueError, match="reserved span fields"):
        telemetry.record_causal_interval(
            state,
            span_id="safe",
            name="safe",
            category="machine_local_execution",
            started_at=BASE,
            finished_at=BASE + timedelta(seconds=1),
            fields={"span_id": "evil"},
        )


def test_workflow_commit_lag_is_a_child_accounting_span(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="commit-lag",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="commit-lag-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    _wait(projects_root, "commit-lag")
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    evidence = {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    }
    kernel.commit_phase_job(
        "run", "commit-lag", evidence=evidence, pipeline_dir=projects_root
    )

    committed = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    spans = committed["causal_telemetry"]["spans"]
    reconcile_span = next(
        span for span in spans if span.get("span_id") == "reconcile:commit-lag"
    )
    transition_span = next(
        span for span in spans if span.get("kind") == "workflow_transition"
        and span.get("job_id") == "commit-lag"
    )
    assert transition_span["category"] == "accounting_reconciliation"
    assert transition_span["parent_span_id"] == reconcile_span["parent_span_id"]
    assert transition_span["started_at"] == reconcile_span["finished_at"]
    assert transition_span["outcome"] == "succeeded"


def test_all_required_causal_categories_are_accounted_without_relabeling() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-categories", started_at=BASE),
    }
    cases = [
        ("machine_local_execution", "machine_execution_seconds"),
        ("provider_network_wait", "provider_wait_seconds"),
        ("agent_editorial_work", "editorial_wall_seconds"),
        ("browser_render_execution", "browser_render_seconds"),
        ("review_evidence_assembly", "review_phase_seconds"),
        ("accounting_reconciliation", "accounting_lag_seconds"),
        ("automated_recovery", "automated_recovery_seconds"),
        ("human_idle", "human_idle_seconds"),
    ]
    for index, (category, _metric) in enumerate(cases):
        telemetry.record_causal_interval(
            state,
            span_id=f"category-{index}",
            name=category,
            category=category,
            started_at=BASE + timedelta(seconds=index),
            finished_at=BASE + timedelta(seconds=index + 1),
        )
    result = workflow.phase_time_accounting(
        state, now=BASE + timedelta(seconds=len(cases))
    )
    for _category, metric in cases:
        assert result[metric] == 1.0
    assert result["causal_coverage_percent"] == 100.0
    assert result["unattributed_wall_seconds"] == 0.0


def test_structural_phase_span_does_not_inflate_render_duration() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-render", started_at=BASE),
    }
    telemetry.record_causal_interval(
        state,
        span_id="phase:render:1",
        name="render phase container",
        category="agent_editorial_work",
        started_at=BASE,
        finished_at=BASE + timedelta(seconds=100),
        kind="phase_attempt",
        count_toward_wall=False,
    )
    telemetry.record_causal_interval(
        state,
        span_id="renderer",
        name="actual browser renderer",
        category="browser_render_execution",
        started_at=BASE + timedelta(seconds=20),
        finished_at=BASE + timedelta(seconds=30),
        parent_span_id="phase:render:1",
    )
    result = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=100))
    assert result["workflow_wall_seconds"] == 100.0
    assert result["browser_render_seconds"] == 10.0
    assert result["causal_covered_seconds"] == 10.0
    assert result["unattributed_wall_seconds"] == 90.0


def test_telemetry_reporting_failure_preserves_execution_truth_and_blocks_commit(
    tmp_path: Path, monkeypatch
) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="telemetry-failure",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="telemetry-failure-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )

    durable = workflow.reconcile_workflow_job(
        "run", "telemetry-failure", pipeline_dir=projects_root
    )
    for _ in range(100):
        if durable.get("status") in {"succeeded", "failed", "interrupted"}:
            break
        time.sleep(0.05)
        durable = workflow.reconcile_workflow_job(
            "run", "telemetry-failure", pipeline_dir=projects_root
        )
    assert durable["executionOutcome"] == "succeeded"

    original = kernel._persist_job_causal_span
    monkeypatch.setattr(
        kernel,
        "_persist_job_causal_span",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("telemetry storage failed")),
    )
    reconciled = kernel.reconcile_phase_job(
        "run", "telemetry-failure", pipeline_dir=projects_root
    )
    assert reconciled["executionOutcome"] == "succeeded"
    envelope = kernel.load_execution_envelope(
        "run", "telemetry-failure", pipeline_dir=projects_root
    )
    assert envelope["executionOutcome"] == "succeeded"
    assert envelope["telemetryOutcome"] == "failed"
    assert "telemetry storage failed" in envelope["telemetryError"]
    assert workflow.load_workflow_state(
        "run", pipeline_dir=projects_root
    )["next_phase"] == "prepare_inputs"

    with pytest.raises(kernel.PersianRunKernelError, match="causal telemetry"):
        kernel.commit_phase_job(
            "run", "telemetry-failure", pipeline_dir=projects_root
        )

    monkeypatch.setattr(kernel, "_persist_job_causal_span", original)
    recovered = kernel.reconcile_phase_job(
        "run", "telemetry-failure", pipeline_dir=projects_root
    )
    assert recovered["executionOutcome"] == "succeeded"
    envelope = kernel.load_execution_envelope(
        "run", "telemetry-failure", pipeline_dir=projects_root
    )
    assert envelope["telemetryOutcome"] == "succeeded"
    assert "telemetryError" not in envelope

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    committed = kernel.commit_phase_job(
        "run",
        "telemetry-failure",
        evidence={
            "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
            "narration_sha256": state["input"]["narration"]["sha256"],
        },
        pipeline_dir=projects_root,
    )
    assert committed["next_phase"] == "align_script_timing"


def test_transition_telemetry_failure_cannot_advance_workflow_state(
    tmp_path: Path, monkeypatch
) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="transition-reporting-failure",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="transition-reporting-failure-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    _wait(projects_root, "transition-reporting-failure")
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    evidence = {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    }

    monkeypatch.setattr(
        kernel,
        "_persist_transition_causal_span",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("transition telemetry failed")),
    )
    with pytest.raises(ValueError, match="transition telemetry failed"):
        kernel.commit_phase_job(
            "run",
            "transition-reporting-failure",
            evidence=evidence,
            pipeline_dir=projects_root,
        )

    after = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    assert after["next_phase"] == "prepare_inputs"
    assert "prepare_inputs" not in after["completed_phases"]
    envelope = kernel.load_execution_envelope(
        "run", "transition-reporting-failure", pipeline_dir=projects_root
    )
    assert envelope["executionOutcome"] == "succeeded"


def test_fresh_trace_reports_zero_percent_coverage_instead_of_legacy_fallback(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=20))
    assert accounting["workflow_wall_seconds"] == 20.0
    assert accounting["causal_covered_seconds"] == 0.0
    assert accounting["causal_coverage_percent"] == 0.0
    assert accounting["unattributed_wall_seconds"] == 20.0
    assert accounting["telemetry_span_count"] == 0



def test_one_shot_run_reconciles_and_commits_without_manual_status_round_trip(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    evidence = {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    }

    committed = kernel.run_phase_job(
        "run",
        job_id="one-shot",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="one-shot-v1",
        telemetry_category="machine_local_execution",
        evidence=evidence,
        pipeline_dir=projects_root,
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
        now=BASE + timedelta(seconds=5),
    )

    assert committed["next_phase"] == "align_script_timing"
    envelope = kernel.load_execution_envelope("run", "one-shot", pipeline_dir=projects_root)
    assert envelope["executionOutcome"] == "succeeded"
    assert envelope["telemetryOutcome"] == "succeeded"
    assert envelope["workflowTransitionOutcome"] == "succeeded"
    spans = workflow.load_workflow_state("run", pipeline_dir=projects_root)["causal_telemetry"]["spans"]
    assert sum(span.get("span_id") == "job:one-shot" for span in spans) == 1
    assert any(str(span.get("span_id") or "").startswith("reconcile:one-shot") for span in spans)
    assert sum(span.get("kind") == "workflow_transition" and span.get("job_id") == "one-shot" for span in spans) == 1


def test_one_shot_run_timeout_preserves_durable_job_for_later_reconciliation(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    child = (
        "import json, os, time; from pathlib import Path; time.sleep(0.25); "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps({'success': True}))"
    )

    with pytest.raises(kernel.PersianRunKernelError, match="still running"):
        kernel.run_phase_job(
            "run",
            job_id="slow-one-shot",
            phase="prepare_inputs",
            argv=["python", "-c", child],
            idempotence_key="slow-one-shot-v1",
            telemetry_category="machine_local_execution",
            pipeline_dir=projects_root,
            poll_interval_seconds=0.01,
            timeout_seconds=0.02,
            now=BASE + timedelta(seconds=5),
        )

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    assert state["next_phase"] == "prepare_inputs"
    envelope = kernel.load_execution_envelope("run", "slow-one-shot", pipeline_dir=projects_root)
    assert envelope["workflowTransitionOutcome"] == "pending"

    reconciled = _wait(projects_root, "slow-one-shot")
    assert reconciled["executionOutcome"] == "succeeded"
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    committed = kernel.commit_phase_job(
        "run",
        "slow-one-shot",
        evidence={
            "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
            "narration_sha256": state["input"]["narration"]["sha256"],
        },
        pipeline_dir=projects_root,
    )
    assert committed["next_phase"] == "align_script_timing"


def test_one_shot_run_is_idempotent_after_successful_commit(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    evidence = {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    }
    kwargs = dict(
        job_id="idempotent-one-shot",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="idempotent-one-shot-v1",
        telemetry_category="machine_local_execution",
        evidence=evidence,
        pipeline_dir=projects_root,
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
        now=BASE + timedelta(seconds=5),
    )

    first = kernel.run_phase_job("run", **kwargs)
    state_path = projects_root / "run" / ".jobs" / "idempotent-one-shot" / "state.json"
    durable_before = json.loads(state_path.read_text(encoding="utf-8"))
    second = kernel.run_phase_job("run", **kwargs)
    durable_after = json.loads(state_path.read_text(encoding="utf-8"))

    assert first["next_phase"] == second["next_phase"] == "align_script_timing"
    assert durable_before["createdAt"] == durable_after["createdAt"]
    spans = workflow.load_workflow_state("run", pipeline_dir=projects_root)["causal_telemetry"]["spans"]
    assert sum(span.get("span_id") == "job:idempotent-one-shot" for span in spans) == 1



def test_run_kernel_start_cli_accepts_documented_option_order() -> None:
    args = kernel.build_parser().parse_args([
        "start", "project", "job",
        "--phase", "render_final_candidate",
        "--idempotence-key", "render-v1",
        "--telemetry-category", "browser_render_execution",
        "--", "python", "render.py",
    ])
    assert args.command == "start"
    assert args.phase == "render_final_candidate"
    assert args.argv[-2:] == ["python", "render.py"]


def test_run_kernel_cli_exposes_bounded_one_shot_run() -> None:
    args = kernel.build_parser().parse_args([
        "run", "project", "job",
        "--phase", "render_final_candidate",
        "--idempotence-key", "render-v1",
        "--telemetry-category", "browser_render_execution",
        "--poll-interval-seconds", "0.25",
        "--timeout-seconds", "900",
        "--evidence-json", "/tmp/evidence.json",
        "--", "python", "render.py",
    ])
    assert args.command == "run"
    assert args.poll_interval_seconds == 0.25
    assert args.timeout_seconds == 900.0
    assert args.argv[-2:] == ["python", "render.py"]



def test_explicit_work_span_counts_only_prospectively_measured_agent_work(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    started = workflow.start_explicit_work_span(
        "run",
        category="agent_editorial_work",
        name="prepare approved inputs",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    assert started["kind"] == "explicit_work"
    assert started["count_toward_wall"] is True
    assert started["finished_at"] is None

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    assert state["attempts"]["prepare_inputs"] == 1
    phase = next(
        span for span in state["causal_telemetry"]["spans"]
        if span.get("kind") == "phase_attempt" and span.get("phase") == "prepare_inputs"
    )
    assert started["parent_span_id"] == phase["span_id"]

    workflow.finish_explicit_work_span(
        "run",
        started["span_id"],
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=25),
    )
    measured = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(measured, now=BASE + timedelta(seconds=30))
    assert accounting["editorial_wall_seconds"] == 20.0
    assert accounting["causal_covered_seconds"] == 20.0
    assert accounting["unattributed_wall_seconds"] == 10.0
    assert accounting["causal_coverage_percent"] == pytest.approx(66.667, abs=0.001)


def test_explicit_work_span_rejects_overlap_instead_of_double_counting(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    workflow.start_explicit_work_span(
        "run",
        category="review_evidence_assembly",
        name="assemble review evidence",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    with pytest.raises(workflow.PersianVideoWorkflowError, match="explicit work span is already open"):
        workflow.start_explicit_work_span(
            "run",
            category="agent_editorial_work",
            name="overlapping editorial work",
            pipeline_dir=projects_root,
            now=BASE + timedelta(seconds=6),
        )


def test_phase_completion_refuses_an_open_explicit_work_span_without_relabeling_it(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    span = workflow.start_explicit_work_span(
        "run",
        category="agent_editorial_work",
        name="prepare approved inputs",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    evidence = {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    }
    with pytest.raises(workflow.PersianVideoWorkflowError, match="finish explicit work span"):
        workflow.complete_phase(
            "run",
            "prepare_inputs",
            evidence=evidence,
            pipeline_dir=projects_root,
            now=BASE + timedelta(seconds=10),
        )
    blocked = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    phase = next(
        item for item in blocked["causal_telemetry"]["spans"]
        if item.get("kind") == "phase_attempt" and item.get("phase") == "prepare_inputs"
    )
    assert phase["finished_at"] is None
    assert blocked["next_phase"] == "prepare_inputs"

    workflow.finish_explicit_work_span(
        "run", span["span_id"], pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=11),
    )
    completed = workflow.complete_phase(
        "run", "prepare_inputs", evidence=evidence, pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=12),
    )
    assert completed["next_phase"] == "align_script_timing"



def test_send_back_interrupts_open_explicit_work_span_in_superseded_phase(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    target_index = workflow.PHASES.index("no_copy_preflight")
    state["completed_phases"] = list(workflow.PHASES[:target_index])
    state["next_phase"] = "no_copy_preflight"
    workflow._write_state(projects_root / "run", state)

    started = workflow.start_explicit_work_span(
        "run",
        category="agent_editorial_work",
        name="author preflight candidate",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    rewound = workflow.request_send_back(
        "run",
        "review_subject_regions",
        reason="subject-region evidence needs revision",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=15),
    )

    spans = rewound["causal_telemetry"]["spans"]
    finished = next(span for span in spans if span.get("span_id") == started["span_id"])
    assert finished["finished_at"] == (BASE + timedelta(seconds=15)).isoformat()
    assert finished["outcome"] == "abandoned_unverified"
    assert finished["count_toward_wall"] is False
    assert finished["measurement_disposition"] == "unverified_abandonment"
    accounting = workflow.phase_time_accounting(rewound, now=BASE + timedelta(seconds=15))
    assert accounting["editorial_wall_seconds"] == 0.0
    assert accounting["unattributed_wall_seconds"] == 15.0
    assert not [
        span for span in spans
        if span.get("count_toward_wall") and not span.get("finished_at")
        and span.get("kind") not in {"run", "phase_attempt"}
    ]
    phase = next(
        span for span in spans
        if span.get("kind") == "phase_attempt" and span.get("phase") == "no_copy_preflight"
    )
    assert phase["outcome"] == "superseded"
    assert rewound["next_phase"] == "review_subject_regions"

def test_explicit_work_cli_exposes_prospective_start_and_finish() -> None:
    start = workflow.build_parser().parse_args([
        "work-start", "project", "--category", "review_evidence_assembly",
        "--name", "final review assembly",
    ])
    assert start.command == "work-start"
    assert start.category == "review_evidence_assembly"
    assert start.name == "final review assembly"

    finish = workflow.build_parser().parse_args([
        "work-finish", "project", "work:final_review:1:1", "--outcome", "succeeded",
    ])
    assert finish.command == "work-finish"
    assert finish.span_id == "work:final_review:1:1"
    assert finish.outcome == "succeeded"

    abandon = workflow.build_parser().parse_args([
        "work-abandon", "project", "work:final_review:1:1", "--reason", "agent interrupted",
    ])
    assert abandon.command == "work-abandon"
    assert abandon.reason == "agent interrupted"


def test_abandon_explicit_work_preserves_unknown_wall_time_and_allows_restart(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    started = workflow.start_explicit_work_span(
        "run", category="agent_editorial_work", name="prepare approved inputs",
        pipeline_dir=projects_root, now=BASE + timedelta(seconds=5),
    )
    recovery_time = BASE + timedelta(hours=4)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="requires a reason"):
        workflow.abandon_explicit_work_span(
            "run", started["span_id"], reason=" ", pipeline_dir=projects_root,
            now=recovery_time,
        )
    recovered = workflow.abandon_explicit_work_span(
        "run", started["span_id"], reason="session ended without work-finish",
        pipeline_dir=projects_root, now=recovery_time,
    )
    assert recovered["started_at"] == started["started_at"]
    assert recovered["finished_at"] == recovery_time.isoformat()
    assert recovered["outcome"] == "abandoned_unverified"
    assert recovered["recovery_reason"] == "session ended without work-finish"
    assert recovered["count_toward_wall"] is False
    assert workflow.abandon_explicit_work_span(
        "run", started["span_id"], reason="retry", pipeline_dir=projects_root,
        now=recovery_time + timedelta(minutes=1),
    ) == recovered
    assert workflow.finish_explicit_work_span(
        "run", started["span_id"], pipeline_dir=projects_root,
        now=recovery_time + timedelta(minutes=1),
    ) == recovered
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(state, now=recovery_time)
    assert accounting["editorial_wall_seconds"] == 0.0
    assert accounting["unattributed_wall_seconds"] == 4 * 3600.0
    restarted = workflow.start_explicit_work_span(
        "run", category="agent_editorial_work", name="resume actual work",
        pipeline_dir=projects_root, now=recovery_time + timedelta(seconds=1),
    )
    assert restarted["span_id"] != started["span_id"]
    workflow.finish_explicit_work_span(
        "run", restarted["span_id"], pipeline_dir=projects_root,
        now=recovery_time + timedelta(seconds=11),
    )
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(state, now=recovery_time + timedelta(seconds=11))
    assert accounting["editorial_wall_seconds"] == 10.0
    assert accounting["unattributed_wall_seconds"] == 4 * 3600 + 1.0


def test_interrupted_finish_does_not_charge_unverified_elapsed_time(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    started = workflow.start_explicit_work_span(
        "run", category="review_evidence_assembly", name="review shot evidence",
        pipeline_dir=projects_root, now=BASE + timedelta(seconds=5),
    )
    recovered = workflow.finish_explicit_work_span(
        "run", started["span_id"], outcome="interrupted",
        pipeline_dir=projects_root, now=BASE + timedelta(hours=2),
    )
    assert recovered["outcome"] == "abandoned_unverified"
    assert recovered["count_toward_wall"] is False
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(state, now=BASE + timedelta(hours=2))
    assert accounting["review_phase_seconds"] == 0.0
    assert accounting["unattributed_wall_seconds"] == 7200.0


def test_failed_transition_retry_does_not_claim_intervening_explicit_work(
    tmp_path: Path,
) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="transition-retry",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="transition-retry-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    _wait(projects_root, "transition-retry")

    with pytest.raises(workflow.PersianVideoWorkflowError, match="authoritative_script_sha256"):
        kernel.commit_phase_job(
            "run", "transition-retry", evidence={}, pipeline_dir=projects_root
        )

    work = workflow.start_explicit_work_span(
        "run",
        category="agent_editorial_work",
        name="repair missing checkpoint evidence",
        pipeline_dir=projects_root,
    )
    work = workflow.finish_explicit_work_span(
        "run", work["span_id"], pipeline_dir=projects_root
    )

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    committed = kernel.commit_phase_job(
        "run",
        "transition-retry",
        evidence={
            "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
            "narration_sha256": state["input"]["narration"]["sha256"],
        },
        pipeline_dir=projects_root,
    )
    assert committed["next_phase"] == "align_script_timing"
    persisted = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    transitions = [
        span
        for span in persisted["causal_telemetry"]["spans"]
        if span.get("kind") == "workflow_transition"
        and span.get("job_id") == "transition-retry"
    ]
    assert [span["outcome"] for span in transitions] == ["failed", "succeeded"]
    assert transitions[1]["started_at"] >= work["finished_at"]


def test_first_transition_starts_after_intervening_explicit_work(
    tmp_path: Path,
) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="first-transition-after-work",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child()],
        idempotence_key="first-transition-after-work-v1",
        telemetry_category="machine_local_execution",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    _wait(projects_root, "first-transition-after-work")

    work = workflow.start_explicit_work_span(
        "run",
        category="agent_editorial_work",
        name="build required checkpoint evidence",
        pipeline_dir=projects_root,
    )
    work = workflow.finish_explicit_work_span(
        "run", work["span_id"], pipeline_dir=projects_root
    )

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    committed = kernel.commit_phase_job(
        "run",
        "first-transition-after-work",
        evidence={
            "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
            "narration_sha256": state["input"]["narration"]["sha256"],
        },
        pipeline_dir=projects_root,
    )
    assert committed["next_phase"] == "align_script_timing"
    persisted = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    transition = next(
        span
        for span in persisted["causal_telemetry"]["spans"]
        if span.get("kind") == "workflow_transition"
        and span.get("job_id") == "first-transition-after-work"
    )
    assert transition["outcome"] == "succeeded"
    assert transition["started_at"] >= work["finished_at"]
