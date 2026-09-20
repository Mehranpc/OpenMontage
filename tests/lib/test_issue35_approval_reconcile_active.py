from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib

from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry

BASE = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)


def test_approved_checkpoint_reconciles_active_next_awaiting_human(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "run"
    project.mkdir()
    candidate = project / "candidate.mp4"
    candidate.write_bytes(b"approved-bytes")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    state = {
        "project_id": "run",
        "projects_root": str(tmp_path),
        "read_allowlist": {"project_root": str(project)},
        "created_at": BASE.isoformat(),
        "status": "active",
        "next_phase": "awaiting_human",
        "completed_phases": ["final_review"],
        "phase_telemetry": {},
        "causal_telemetry": telemetry.new_causal_trace("trace-active-approval", started_at=BASE),
        "performance_slo": {"endToEndSeconds": 2700},
    }
    # Historical runs may carry a structurally closed run span from an earlier
    # terminal candidate even though a later user-directed revision is active.
    # Work performed after that timestamp proves the interval is not human idle.
    telemetry.finish_causal_span(
        state,
        state["causal_telemetry"]["run_span_id"],
        finished_at=BASE + timedelta(seconds=10),
        outcome="awaiting_human",
    )
    telemetry.record_causal_interval(
        state,
        span_id="job:later-render",
        name="later render",
        category="browser_render_execution",
        started_at=BASE + timedelta(seconds=12),
        finished_at=BASE + timedelta(seconds=15),
        parent_span_id=state["causal_telemetry"]["run_span_id"],
        outcome="succeeded",
        kind="durable_job",
        count_toward_wall=True,
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
    assert "awaiting_human" in result["completed_phases"]
    assert result["approval"]["candidate_sha256"] == digest
    assert written["status"] == "completed"
    accounting = result["performance_summary"]
    assert accounting["workflow_wall_seconds"] == 20.0
    assert accounting["human_idle_seconds"] == 0.0
    assert accounting["browser_render_seconds"] == 3.0
