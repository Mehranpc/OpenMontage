from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib

from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry

BASE = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)


def test_phase_residual_backfill_accounts_only_uncovered_review_time() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-h", started_at=BASE),
    }
    telemetry.record_causal_interval(
        state,
        span_id="phase:final_review:1",
        name="final review attempt 1",
        category="agent_editorial_work",
        started_at=BASE,
        finished_at=BASE + timedelta(seconds=30),
        kind="phase_attempt",
        count_toward_wall=False,
        fields={"phase": "final_review", "attempt": 1},
    )
    telemetry.record_causal_interval(
        state,
        span_id="browser-child",
        name="browser evidence",
        category="browser_render_execution",
        started_at=BASE + timedelta(seconds=10),
        finished_at=BASE + timedelta(seconds=20),
        parent_span_id="phase:final_review:1",
        fields={"phase": "final_review", "attempt": 1},
    )

    spans = telemetry.backfill_phase_residual_spans(state, "final_review", 1)
    assert len(spans) == 2
    assert all(span["category"] == "review_evidence_assembly" for span in spans)

    result = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=30))
    assert result["browser_render_seconds"] == 10.0
    assert result["review_phase_seconds"] == 20.0
    assert result["causal_coverage_percent"] == 100.0
    assert result["unattributed_wall_seconds"] == 0.0


def test_reconcile_superseded_attempt_backfills_residual_time() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "status": "active",
        "phase_telemetry": {
            "final_review": [
                {
                    "attempt": 1,
                    "started_at": BASE.isoformat(),
                    "finished_at": None,
                    "outcome": "running",
                },
                {
                    "attempt": 2,
                    "started_at": (BASE + timedelta(seconds=10)).isoformat(),
                    "finished_at": None,
                    "outcome": "running",
                },
            ]
        },
        "causal_telemetry": telemetry.new_causal_trace("trace-stale", started_at=BASE),
    }
    telemetry.record_phase_attempt_span(state, "final_review", 1, started_at=BASE)
    telemetry.record_phase_attempt_span(
        state, "final_review", 2, started_at=BASE + timedelta(seconds=10)
    )

    telemetry.reconcile_phase_telemetry(state, now=BASE + timedelta(seconds=20))

    spans = state["causal_telemetry"]["spans"]
    residual = [
        span for span in spans
        if span.get("kind") == "phase_residual"
        and span.get("phase") == "final_review"
        and span.get("attempt") == 1
    ]
    assert len(residual) == 1
    assert residual[0]["category"] == "review_evidence_assembly"
    result = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=20))
    assert result["review_phase_seconds"] == 10.0
    assert result["unattributed_wall_seconds"] == 10.0


def test_human_idle_is_explicit_and_reopens_finished_run_trace() -> None:
    state = {
        "created_at": BASE.isoformat(),
        "causal_telemetry": telemetry.new_causal_trace("trace-idle", started_at=BASE),
    }
    telemetry.finish_causal_span(
        state,
        "run:trace-idle",
        finished_at=BASE + timedelta(seconds=10),
        outcome="awaiting_human",
    )

    telemetry.record_human_idle_and_reopen_run(
        state,
        resumed_at=BASE + timedelta(seconds=25),
        reason="explicit user revision",
    )
    run = next(
        span for span in state["causal_telemetry"]["spans"]
        if span["span_id"] == "run:trace-idle"
    )
    assert run["finished_at"] is None
    assert run["outcome"] == "running"
    result = workflow.phase_time_accounting(state, now=BASE + timedelta(seconds=25))
    assert result["human_idle_seconds"] == 15.0
    assert result["causal_coverage_percent"] == 60.0


def test_approved_compose_checkpoint_reconciles_workflow_to_completed(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "run"
    project.mkdir()
    candidate = project / "candidate.mp4"
    candidate.write_bytes(b"approved-bytes")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    trace = telemetry.new_causal_trace("trace-approval", started_at=BASE)
    state = {
        "project_id": "run",
        "projects_root": str(tmp_path),
        "read_allowlist": {"project_root": str(project)},
        "created_at": BASE.isoformat(),
        "status": "awaiting_human",
        "next_phase": None,
        "completed_phases": ["awaiting_human"],
        "phase_telemetry": {},
        "causal_telemetry": trace,
        "performance_slo": {"endToEndSeconds": 2700},
    }
    telemetry.finish_causal_span(
        state,
        trace["run_span_id"],
        finished_at=BASE + timedelta(seconds=10),
        outcome="awaiting_human",
    )
    checkpoint = {
        "version": "1.0",
        "project_id": "run",
        "pipeline_type": "persian-footage",
        "stage": "compose",
        "status": "completed",
        "timestamp": (BASE + timedelta(seconds=20)).isoformat(),
        "human_approval_required": True,
        "human_approved": True,
        "artifacts": {"render_report": {
            "delivery_status": "approved",
            "human_visual_approval": True,
            "persian_text_verified": True,
            "outputs": [{"path": str(candidate), "format": "mp4", "sha256": digest}],
        }},
        "metadata": {"approval_record": {
            "source": "explicit_user_response",
            "candidate_path": str(candidate),
            "candidate_sha256": digest,
        }},
    }
    written = {}
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *a, **k: state)
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *a, **k: checkpoint)
    monkeypatch.setattr(workflow, "_write_state", lambda _root, value: written.update(value))

    result = workflow.reconcile_approved_compose_checkpoint(
        "run", pipeline_dir=tmp_path, now=BASE + timedelta(seconds=20)
    )
    assert result["status"] == "completed"
    assert result["next_phase"] is None
    assert result["approval"]["candidate_sha256"] == digest
    assert written["status"] == "completed"
    accounting = result["performance_summary"]
    assert accounting["human_idle_seconds"] == 10.0
