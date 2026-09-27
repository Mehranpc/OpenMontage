"""Command-cadence accounting (#107 coverage).

Three measured runs showed prompting alone does not make the agent open work spans, so
causal coverage stayed near 27%. Every pipeline command now logs its start and finish
edges. Two edges at most five minutes apart bracket observed agent activity; a longer
silence, or any silence after the run stopped for a person, stays unattributed. Measured
spans always take precedence, so cadence can only fill gaps, never relabel work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry

BASE = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _state(tmp_path: Path) -> dict:
    return {
        "created_at": BASE.isoformat(),
        "status": "active",
        "read_allowlist": {"project_root": str(tmp_path)},
        "causal_telemetry": telemetry.new_causal_trace("trace-cadence", started_at=BASE),
    }


def _edge(root: Path, seconds: float, command: str, edge: str, *, active: bool = True) -> None:
    telemetry.record_command_event(
        root, command=command, edge=edge,
        at=BASE + timedelta(seconds=seconds), run_active=active,
    )


def test_commands_within_the_gap_limit_cover_the_time_between_them(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _edge(tmp_path, 0, "workflow:status", "start")
    _edge(tmp_path, 1, "workflow:status", "finish")
    _edge(tmp_path, 241, "workflow:complete", "start")  # 4 minutes of thinking
    _edge(tmp_path, 242, "workflow:complete", "finish")

    result = telemetry.causal_time_accounting(state, now=BASE + timedelta(seconds=242))

    assert result["agent_command_activity_seconds"] == 242.0
    assert result["causal_coverage_percent"] == 100.0
    assert result["accounting_policy_version"] == "2.1"


def test_silence_longer_than_the_limit_stays_unattributed(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _edge(tmp_path, 0, "workflow:status", "start")
    _edge(tmp_path, 1, "workflow:status", "finish")
    _edge(tmp_path, 1 + telemetry.COMMAND_CADENCE_MAX_GAP_SECONDS + 1, "workflow:status", "start")
    _edge(tmp_path, 1 + telemetry.COMMAND_CADENCE_MAX_GAP_SECONDS + 2, "workflow:status", "finish")

    result = telemetry.causal_time_accounting(
        state, now=BASE + timedelta(seconds=telemetry.COMMAND_CADENCE_MAX_GAP_SECONDS + 3)
    )

    assert result["agent_command_activity_seconds"] == 2.0
    assert result["unattributed_wall_seconds"] == pytest.approx(
        telemetry.COMMAND_CADENCE_MAX_GAP_SECONDS + 1.0
    )


def test_a_long_running_command_counts_its_own_execution(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _edge(tmp_path, 0, "run-kernel:run", "start")
    _edge(tmp_path, 900, "run-kernel:run", "finish")

    result = telemetry.causal_time_accounting(state, now=BASE + timedelta(seconds=900))

    assert result["agent_command_activity_seconds"] == 900.0


def test_wait_after_a_stop_is_never_agent_activity(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _edge(tmp_path, 0, "workflow:complete", "start")
    _edge(tmp_path, 1, "workflow:complete", "finish", active=False)  # stopped for a person
    _edge(tmp_path, 120, "workflow:budget-decision", "start", active=False)
    _edge(tmp_path, 121, "workflow:budget-decision", "finish")

    result = telemetry.causal_time_accounting(state, now=BASE + timedelta(seconds=121))

    assert result["agent_command_activity_seconds"] == 2.0
    assert result["unattributed_wall_seconds"] == 119.0


def test_measured_spans_take_precedence_and_are_not_double_counted(tmp_path: Path) -> None:
    state = _state(tmp_path)
    telemetry.record_causal_interval(
        state, span_id="job:render", name="render", category="browser_render_execution",
        started_at=BASE + timedelta(seconds=10), finished_at=BASE + timedelta(seconds=70),
        kind="durable_job",
    )
    _edge(tmp_path, 0, "workflow:status", "start")
    _edge(tmp_path, 100, "workflow:status", "start")

    result = telemetry.causal_time_accounting(state, now=BASE + timedelta(seconds=100))

    assert result["browser_render_seconds"] == 60.0
    assert result["agent_command_activity_seconds"] == 40.0
    assert result["causal_covered_seconds"] == 100.0
    assert result["explicit_concurrency_seconds"] == 0.0


def test_torn_log_line_is_ignored(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _edge(tmp_path, 0, "workflow:status", "start")
    _edge(tmp_path, 10, "workflow:status", "finish")
    with telemetry.command_events_path(tmp_path).open("a", encoding="utf-8") as handle:
        handle.write('{"at": "2026-09-27T12:0')

    result = telemetry.causal_time_accounting(state, now=BASE + timedelta(seconds=10))

    assert result["agent_command_activity_seconds"] == 10.0


def _bootstrap(tmp_path: Path) -> Path:
    projects_root = tmp_path / "projects"
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"stable-audio-input")
    workflow.bootstrap_persian_video(
        title="cadence", narration_path=str(narration),
        approved_script="متن تأییدشده برای آزمون", project_id="run",
        pipeline_dir=projects_root, backlot_opener=lambda _project_id: 0, now=BASE,
    )
    return projects_root


def test_workflow_cli_logs_both_edges_even_when_the_command_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = _bootstrap(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", projects_root)

    assert workflow.main(["status", "run"]) == 0
    with pytest.raises(SystemExit):
        workflow.main(["complete", "run", "--phase", "final_review"])

    log = telemetry.command_events_path(projects_root / "run")
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [(e["command"], e["edge"]) for e in events] == [
        ("workflow:status", "start"), ("workflow:status", "finish"),
        ("workflow:complete", "start"), ("workflow:complete", "finish"),
    ]
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    assert "command_events" not in state["causal_telemetry"]


def test_command_log_does_not_mask_a_stall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects_root = _bootstrap(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", projects_root)
    workflow.main(["status", "run"])

    last_path, _ = workflow._last_project_write(projects_root / "run")

    assert last_path is not None and not last_path.startswith(".telemetry")


def test_edge_recording_never_breaks_a_command_without_state(tmp_path: Path) -> None:
    workflow.record_cli_command_edge("missing", "workflow:status", "start", pipeline_dir=tmp_path)
    assert not (tmp_path / "missing").exists()
