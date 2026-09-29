"""#342: time a run sits parked is not charged to its wall budget.

On the 2026-09-29 Mac run (persian-video-20260929-051254-e6b68abc) the wall budget
stopped the run at 19857s against 11580s. Most of that window was the run waiting:
on budget questions, and for hours on code fixes (#333, #335, #337) while no
pipeline command ran. ``resume`` already treats a 15-minute silence as idle; the
budget did not, so every pause came back as a larger extension the user had to
approve.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import (
    IDLE_STALL_SECONDS,
    PersianVideoWorkflowError,
    enforce_front_door_budget,
    load_workflow_state,
    workflow_status,
)
from lib.persian_workflow_telemetry import (
    command_events_path,
    parked_wall_seconds,
    record_causal_interval,
)
from tests.lib.test_persian_video_workflow import BASE, _bootstrap

PROJECT = "run"


def _setup(tmp_path: Path) -> tuple[Path, int]:
    _bootstrap(tmp_path)
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["budget_window_started_at"] = BASE.isoformat()
    workflow._write_state(tmp_path / PROJECT, state)
    return tmp_path / PROJECT, int(state["budgets"]["max_wall_time_minutes"]) * 60


def _commands(root: Path, *pairs: tuple[str, float, float]) -> None:
    """Write command start/finish edges (seconds after BASE) to the command log."""
    path = command_events_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for name, start, finish in pairs:
            for edge, at in (("start", start), ("finish", finish)):
                handle.write(json.dumps({
                    "at": (BASE + timedelta(seconds=at)).isoformat(),
                    "command": name, "edge": edge, "run_active": True,
                }) + "\n")


def test_an_unattended_silence_does_not_trip_the_wall_budget(tmp_path: Path) -> None:
    root, limit = _setup(tmp_path)
    # Work for 10 minutes, park for two hours (nothing runs), then come back.
    _commands(
        root,
        ("workflow:asset-search", 0, 30),
        ("workflow:asset-candidate-review", 300, 320),
        ("workflow:asset-candidate-select", 600, 610),
        ("workflow:reconcile-plan", 600 + 7200, 600 + 7210),
    )
    now = BASE + timedelta(seconds=600 + 7220)
    assert (now - BASE).total_seconds() > limit  # the raw window is far over

    state = enforce_front_door_budget(
        PROJECT, operation="workflow:assets:build-manifest", pipeline_dir=tmp_path, now=now,
    )
    assert not state.get("budget_stop")
    status = workflow_status(PROJECT, pipeline_dir=tmp_path, now=now)["operational_summary"]
    assert status["parked_seconds"] == pytest.approx(7190, abs=1)
    assert status["charged_wall_seconds"] == pytest.approx(630, abs=1)
    line = workflow.format_status_line(workflow_status(PROJECT, pipeline_dir=tmp_path, now=now))
    assert "charged=6" in line


def test_status_calls_during_the_pause_do_not_break_the_silence(tmp_path: Path) -> None:
    root, limit = _setup(tmp_path)
    # A helper polls status every ten minutes while nobody drives the run.
    polls = [("workflow:status", 600 + 600 * i, 600 + 600 * i + 1) for i in range(1, 12)]
    _commands(root, ("workflow:asset-search", 0, 600), *polls,
              ("workflow:asset-candidate-review", 600 + 7200, 600 + 7210))
    state = enforce_front_door_budget(
        PROJECT, operation="workflow:asset-candidate-select", pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=600 + 7220),
    )
    assert not state.get("budget_stop")


def test_steady_work_past_the_budget_still_stops(tmp_path: Path) -> None:
    """Parking is not a blank cheque: commands every few minutes are real work."""
    root, limit = _setup(tmp_path)
    step = 240  # under the 15-minute silence threshold
    _commands(root, *[
        ("workflow:asset-candidate-review", i * step, i * step + 20)
        for i in range(limit // step + 3)
    ])
    now = BASE + timedelta(seconds=(limit // step + 3) * step)
    with pytest.raises(PersianVideoWorkflowError, match="wall_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT, operation="workflow:asset-search", pipeline_dir=tmp_path, now=now,
        )
    stop = load_workflow_state(PROJECT, pipeline_dir=tmp_path)["budget_stop"]
    assert stop["parked_seconds"] == 0
    assert stop["observed_seconds"] == pytest.approx(stop["window_seconds"])


def test_a_long_durable_job_is_work_not_silence(tmp_path: Path) -> None:
    root, limit = _setup(tmp_path)
    _commands(root, ("workflow:asset-search", 0, 10),
              ("workflow:asset-candidate-review", limit + 100, limit + 110))
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    # A provider download ran for the whole gap between the two commands.
    record_causal_interval(
        state, span_id="job:render", name="render", category="browser_render_execution",
        started_at=BASE + timedelta(seconds=10), finished_at=BASE + timedelta(seconds=limit + 100),
        parent_span_id=state["causal_telemetry"]["run_span_id"], outcome="succeeded",
        kind="durable_job", count_toward_wall=True,
    )
    workflow._write_state(root, state)
    with pytest.raises(PersianVideoWorkflowError, match="wall_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT, operation="workflow:asset-search", pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=limit + 120),
        )


def test_a_recorded_human_wait_is_not_charged(tmp_path: Path) -> None:
    root, limit = _setup(tmp_path)
    _commands(root, *[
        ("workflow:asset-candidate-review", i * 120, i * 120 + 10) for i in range(10)
    ], ("workflow:budget-decision", 1300 + limit, 1301 + limit))
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    record_causal_interval(
        state, span_id="human-idle:1", name="human idle 1", category="human_idle",
        started_at=BASE + timedelta(seconds=1200), finished_at=BASE + timedelta(seconds=1200 + limit),
        parent_span_id=state["causal_telemetry"]["run_span_id"], outcome="succeeded",
        kind="human_idle", count_toward_wall=True,
    )
    parked = parked_wall_seconds(
        state, since=BASE, now=BASE + timedelta(seconds=1300 + limit),
        silence_seconds=IDLE_STALL_SECONDS,
    )
    # The human wait and the command silence cover the same stretch: counted once.
    assert parked["parked_seconds"] == pytest.approx(1300 + limit - 1090, abs=1)
    assert parked["human_idle_seconds"] == pytest.approx(limit, abs=1)
