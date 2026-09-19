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
