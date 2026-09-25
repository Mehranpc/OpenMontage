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


def _write_attempt_state(
    tmp_path: Path,
    *,
    current_cycle: int,
    attempt_cycle: int,
    duration_seconds: float,
    tag: bool = True,
) -> None:
    """Persist one recorded phase attempt of the given duration on an existing project."""
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["next_phase"] = PHASE
    state["user_revision_cycles"] = current_cycle
    entry = {
        "attempt": 1,
        "started_at": BASE.isoformat(),
        "finished_at": (BASE + timedelta(seconds=duration_seconds)).isoformat(),
        "duration_seconds": duration_seconds,
        "execution_class": "editorial",
        "outcome": "superseded",
    }
    if tag:
        entry["revision_cycle"] = attempt_cycle
    state["phase_telemetry"] = {PHASE: [entry]}
    workflow._write_state(tmp_path / PROJECT, state)


def _record_attempt(
    tmp_path: Path,
    *,
    current_cycle: int,
    attempt_cycle: int,
    duration_seconds: float,
    tag: bool = True,
) -> None:
    """Bootstrap, then persist one recorded phase attempt of the given duration."""
    _bootstrap(tmp_path)
    _write_attempt_state(
        tmp_path,
        current_cycle=current_cycle,
        attempt_cycle=attempt_cycle,
        duration_seconds=duration_seconds,
        tag=tag,
    )


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


def test_budget_decision_is_exempt_from_the_front_door_guard() -> None:
    """The command that exists to satisfy a stop must not itself be blocked by it.

    The CLI runs the front-door budget guard before every command, so without this
    exemption the first ``budget-decision`` is refused with the very message it
    exists to satisfy (#152 review F2).
    """
    assert "budget-decision" in workflow._BUDGET_GUARD_EXEMPT_COMMANDS


def test_revision_from_a_terminal_stop_leaves_the_phase_attemptable(
    tmp_path: Path,
) -> None:
    """A terminal stop never closes the attempt it interrupted, so the revision it
    invites must not then treat that abandoned attempt as the live one — otherwise
    the front door skips recording a new attempt and the phase can never complete
    (#152 review F1)."""
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
                "finished_at": None,
                "duration_seconds": None,
                "execution_class": "editorial",
                "outcome": "running",
            }
        ]
    }
    workflow._write_state(tmp_path / PROJECT, state)

    workflow.request_send_back(
        PROJECT,
        PHASE,
        reason="user-directed revision after a terminal stop",
        user_directed_revision=True,
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=60),
    )
    revised = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    assert revised["phase_telemetry"][PHASE][-1]["outcome"] == "superseded"

    workflow.start_explicit_work_span(
        PROJECT,
        category="agent_editorial_work",
        name="revision work",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=90),
    )
    after = load_workflow_state(PROJECT, pipeline_dir=tmp_path)

    assert after["attempts"].get(PHASE) == 1
    assert after["phase_telemetry"][PHASE][-1]["revision_cycle"] == 1
    assert after["phase_telemetry"][PHASE][-1]["outcome"] == "running"


def test_untagged_attempts_belong_to_the_first_cycle(tmp_path: Path) -> None:
    """Attempts recorded before cycle tagging must default to the first cycle, in
    both directions: the observed project's stale attempt is excluded, while a run
    that has never been revised still counts its own attempt."""
    _bootstrap(tmp_path)
    # The observed project: revised, so an untagged attempt belongs to the cycle the
    # revision replaced.
    _write_attempt_state(
        tmp_path, current_cycle=1, attempt_cycle=0, duration_seconds=OVERRUN, tag=False
    )
    assert enforce_front_door_budget(
        PROJECT,
        operation="workflow:work-start",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=30),
    )["status"] == "active"

    # A run that has never been revised still counts it.
    _write_attempt_state(
        tmp_path, current_cycle=0, attempt_cycle=0, duration_seconds=OVERRUN, tag=False
    )
    with pytest.raises(PersianVideoWorkflowError, match="phase_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT,
            operation="workflow:work-start",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=30),
        )


def test_extension_is_scoped_to_the_window_it_was_granted_in(tmp_path: Path) -> None:
    """A grant belongs to its window: it must not inflate the budget a later,
    freshly-opened window believes it has (#152 review F3)."""
    limit = _wall_stopped_run(tmp_path)
    resolve_budget_stop(
        PROJECT,
        decision="continue_with_extension",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=limit + 300),
    )
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    decided_at = workflow._parse_timestamp(
        state["budget_decisions"][-1]["decided_at"]
    )
    assert workflow._granted_extension_seconds(
        state, reason="wall_budget_exceeded", since=decided_at
    ) > 0

    # A fresh window opened afterwards must not inherit the old grant.
    state["budget_window_started_at"] = (decided_at + timedelta(days=7)).isoformat()
    workflow._write_state(tmp_path / PROJECT, state)
    reloaded = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    later_window = workflow._parse_timestamp(reloaded["budget_window_started_at"])
    assert workflow._granted_extension_seconds(
        reloaded, reason="wall_budget_exceeded", since=later_window
    ) == 0.0


def test_continue_to_preview_records_the_skipped_phases(tmp_path: Path) -> None:
    """Previewing skips forward; the abandoned phases must be recorded rather than
    left implied by a pointer the run never earned (#152 review F5)."""
    _stopped_run(tmp_path)
    state = resolve_budget_stop(
        PROJECT,
        decision="continue_to_preview",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=120),
    )

    assert state["next_phase"] == "render_opening_candidate"
    assert state["budget_decisions"][-1]["skipped_phases"] == [PHASE]
    assert PHASE not in (state.get("completed_phases") or [])


def test_a_decision_that_leaves_another_budget_outstanding_surfaces_it(
    tmp_path: Path,
) -> None:
    """A run can be over more than one budget. Releasing one must show the operator
    whatever is still outstanding, instead of letting their next command fail on a
    stop they were never shown (#152 review F6)."""
    _record_attempt(
        tmp_path, current_cycle=0, attempt_cycle=0, duration_seconds=OVERRUN
    )
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["budget_window_started_at"] = BASE.isoformat()
    workflow._write_state(tmp_path / PROJECT, state)
    limit = int(state["budgets"]["max_wall_time_minutes"]) * 60
    late = BASE + timedelta(seconds=limit + 500)

    with pytest.raises(PersianVideoWorkflowError, match="wall_budget_exceeded"):
        enforce_front_door_budget(
            PROJECT, operation="workflow:work-start", pipeline_dir=tmp_path, now=late
        )

    resolved = resolve_budget_stop(
        PROJECT,
        decision="continue_with_extension",
        pipeline_dir=tmp_path,
        now=late,
    )

    assert resolved["budget_decisions"][-1]["decision"] == "continue_with_extension"
    assert resolved["status"] == "failed"
    assert resolved["budget_stop"]["reason"] == "phase_budget_exceeded"


