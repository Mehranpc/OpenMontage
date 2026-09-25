"""#152: a sanctioned revision cycle must open a fresh phase budget, and every
advertised budget stop must be actionable through a front-door command.

Observed on the fresh cold L3 run from `main` @ `dc5d1ed`. A user-directed
revision opened a fresh wall window and then the *phase* budget tripped 29
seconds later, because the superseded attempt from the previous revision cycle
still drove phase-elapsed accounting (2195s observed against a 600s threshold).
The stop's own instruction -- "resume with an explicit budget decision" -- then
had no command to enact it, and nothing ever cleared the persisted stop, so the
run was permanently unreachable through supported commands.

These tests assert persisted state through the front-door seam, not logs or
internal helpers.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import (
    PHASE_SLO_SECONDS,
    PersianVideoWorkflowError,
    enforce_front_door_budget,
    load_workflow_state,
    resolve_budget_stop,
)
from tests.lib.test_persian_video_workflow import BASE, _bootstrap

PROJECT = "run"
PHASE = "no_copy_preflight"
PHASE_LIMIT = 2 * PHASE_SLO_SECONDS[PHASE]  # 600s
OVERRUN = float(PHASE_LIMIT + 1600)


def _record_attempt(
    tmp_path: Path,
    *,
    current_cycle: int,
    attempt_cycle: int,
    duration_seconds: float,
) -> None:
    """Bootstrap, then persist one recorded phase attempt of the given duration."""
    _bootstrap(tmp_path)
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["next_phase"] = PHASE
    state["user_revision_cycles"] = current_cycle
    state["phase_telemetry"] = {
        PHASE: [
            {
                "attempt": 1,
                "started_at": BASE.isoformat(),
                "finished_at": (BASE + timedelta(seconds=duration_seconds)).isoformat(),
                "duration_seconds": duration_seconds,
                "execution_class": "editorial",
                "outcome": "superseded",
                "revision_cycle": attempt_cycle,
            }
        ]
    }
    workflow._write_state(tmp_path / PROJECT, state)


def test_previous_revision_cycle_attempt_does_not_consume_the_new_phase_budget(
    tmp_path: Path,
) -> None:
    """The exact L3 failure: a superseded attempt from the prior cycle must not
    re-trip the phase budget in the fresh revision cycle."""
    _record_attempt(
        tmp_path, current_cycle=1, attempt_cycle=0, duration_seconds=OVERRUN
    )

    state = enforce_front_door_budget(
        PROJECT,
        operation="workflow:work-start",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=30),
    )

    assert state["status"] == "active"
    assert not state.get("budget_stop")


def test_current_revision_cycle_attempt_still_stops_the_run(tmp_path: Path) -> None:
    """Scoping must not disable the watchdog: a genuine overrun in the live cycle
    still stops the run."""
    _record_attempt(
        tmp_path, current_cycle=1, attempt_cycle=1, duration_seconds=OVERRUN
    )

    with pytest.raises(PersianVideoWorkflowError, match="phase_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT,
            operation="workflow:work-start",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=30),
        )

    stopped = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    assert stopped["status"] == "failed"
    assert stopped["budget_stop"]["reason"] == "phase_budget_exceeded"
    assert stopped["budget_stop"]["quality_disposition"] == "needs_decision"


def test_user_directed_revision_admits_the_next_front_door_operation(
    tmp_path: Path,
) -> None:
    """The operator's actual recovery path, exactly as the L3 run took it: a
    terminal workflow carrying a superseded attempt from the previous cycle is
    revised, and the next front-door operation must be admitted."""
    _bootstrap(tmp_path)
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["status"] = "needs_revision"
    state["next_phase"] = None
    state["user_revision_cycles"] = 0
    state["phase_telemetry"] = {
        PHASE: [
            {
                "attempt": 1,
                "started_at": BASE.isoformat(),
                "finished_at": (BASE + timedelta(seconds=OVERRUN)).isoformat(),
                "duration_seconds": OVERRUN,
                "execution_class": "editorial",
                "outcome": "superseded",
                "revision_cycle": 0,
            }
        ]
    }
    workflow._write_state(tmp_path / PROJECT, state)

    workflow.request_send_back(
        PROJECT,
        PHASE,
        reason="user-directed revision after terminal revision stop",
        user_directed_revision=True,
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=60),
    )

    state = enforce_front_door_budget(
        PROJECT,
        operation="workflow:work-start",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=90),
    )
    assert state["status"] == "active"
    assert not state.get("budget_stop")
    assert state["user_revision_cycles"] == 1


def _stopped_run(tmp_path: Path) -> dict:
    """Drive the project into a persisted, unresolved budget stop."""
    _record_attempt(
        tmp_path, current_cycle=0, attempt_cycle=0, duration_seconds=OVERRUN
    )
    with pytest.raises(PersianVideoWorkflowError, match="phase_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT,
            operation="workflow:work-start",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=30),
        )
    return load_workflow_state(PROJECT, pipeline_dir=tmp_path)


def test_continue_with_extension_resolves_the_stop_and_records_the_decision(
    tmp_path: Path,
) -> None:
    stopped = _stopped_run(tmp_path)
    advertised = next(
        option
        for option in stopped["budget_stop"]["options"]
        if option["action"] == "continue_with_extension"
    )

    state = resolve_budget_stop(
        PROJECT,
        decision="continue_with_extension",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=120),
    )

    assert state["status"] == "active"
    assert not state.get("budget_stop")
    recorded = state["budget_decisions"][-1]
    assert recorded["decision"] == "continue_with_extension"
    assert recorded["observed_seconds"] == pytest.approx(OVERRUN)
    assert recorded["threshold_seconds"] == PHASE_LIMIT
    assert recorded["extension_minutes"] >= advertised["minimum_extra_minutes"]

    # The run is usable again: the next front-door operation is admitted.
    assert enforce_front_door_budget(
        PROJECT,
        operation="workflow:work-start",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=150),
    )["status"] == "active"


def _wall_stopped_run(tmp_path: Path) -> int:
    """Drive a wall-budget stop; returns the wall limit in seconds."""
    _bootstrap(tmp_path)
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["budget_window_started_at"] = BASE.isoformat()
    limit = int(state["budgets"]["max_wall_time_minutes"]) * 60
    workflow._write_state(tmp_path / PROJECT, state)
    with pytest.raises(PersianVideoWorkflowError, match="wall_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT,
            operation="workflow:work-start",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=limit + 300),
        )
    return limit


def test_extension_grants_only_what_it_grants(tmp_path: Path) -> None:
    """An extension must not be a blank cheque: the tripped budget still closes."""
    limit = _wall_stopped_run(tmp_path)
    state = resolve_budget_stop(
        PROJECT,
        decision="continue_with_extension",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=limit + 300),
    )
    granted = state["budget_decisions"][-1]["extension_minutes"] * 60
    assert granted >= 300

    # Just inside the granted allowance the run continues.
    enforce_front_door_budget(
        PROJECT,
        operation="workflow:work-start",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=limit + granted - 1),
    )
    # Past it the watchdog closes the run again.
    with pytest.raises(PersianVideoWorkflowError, match="wall_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT,
            operation="workflow:work-start",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=limit + granted + 1),
        )


def test_continue_to_preview_rewinds_to_the_advertised_phase(tmp_path: Path) -> None:
    stopped = _stopped_run(tmp_path)
    advertised = next(
        option
        for option in stopped["budget_stop"]["options"]
        if option["action"] == "continue_to_preview"
    )

    state = resolve_budget_stop(
        PROJECT,
        decision="continue_to_preview",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=120),
    )

    assert state["status"] == "active"
    assert not state.get("budget_stop")
    assert state["next_phase"] == advertised["preview_phase"]
    assert state["budget_decisions"][-1]["decision"] == "continue_to_preview"


def test_stop_terminalizes_truthfully(tmp_path: Path) -> None:
    stopped = _stopped_run(tmp_path)
    assert "stop" in [o["action"] for o in stopped["budget_stop"]["options"]]

    state = resolve_budget_stop(
        PROJECT,
        decision="stop",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=120),
    )

    assert state["status"] == "failed"
    assert not state.get("budget_stop")
    assert state["next_phase"] is None
    assert state["budget_decisions"][-1]["decision"] == "stop"
    # A deliberately abandoned run admits no further work.
    with pytest.raises(PersianVideoWorkflowError, match="active workflow phase"):
        workflow.start_explicit_work_span(
            PROJECT,
            category="agent_editorial_work",
            name="should not start",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=150),
        )


def test_resolving_an_unstopped_run_is_refused(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="no budget stop"):
        resolve_budget_stop(
            PROJECT,
            decision="continue_with_extension",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=30),
        )


def test_unknown_decision_is_refused(tmp_path: Path) -> None:
    _stopped_run(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="unknown budget decision"):
        resolve_budget_stop(
            PROJECT,
            decision="continue_forever",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=120),
        )


def test_budget_decision_is_idempotent(tmp_path: Path) -> None:
    _stopped_run(tmp_path)
    first = resolve_budget_stop(
        PROJECT,
        decision="continue_with_extension",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=120),
    )
    second = resolve_budget_stop(
        PROJECT,
        decision="continue_with_extension",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=180),
    )

    assert len(second["budget_decisions"]) == len(first["budget_decisions"]) == 1
    assert second["status"] == "active"


def test_cli_exposes_the_budget_decision_command() -> None:
    """The remedy a stop advertises must be reachable from the front door."""
    parser = workflow.build_parser()
    args = parser.parse_args(
        ["budget-decision", "abc-1", "--decision", "continue_with_extension"]
    )
    assert args.command == "budget-decision"
    assert args.decision == "continue_with_extension"
    assert args.extension_minutes is None
    assert set(workflow._BUDGET_DECISIONS) == {
        "continue_with_extension",
        "continue_to_preview",
        "stop",
    }
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["budget-decision", "abc-1", "--decision", "continue_forever"]
        )

