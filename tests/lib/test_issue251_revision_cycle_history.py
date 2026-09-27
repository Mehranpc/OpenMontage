"""#251: a user-directed revision keeps a fresh budget but not a fresh history.

After one revision on the f13d914 run, the report said send_backs 0, no plan
reconciliations and no phase SLO overrun, although acquire_assets had overrun and three
send-backs had happened.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import load_workflow_state
from tests.lib.test_issue152_revision_budget_decisions import OVERRUN, PHASE, PROJECT
from tests.lib.test_persian_video_workflow import BASE, _bootstrap


def _revised(tmp_path: Path) -> dict:
    _bootstrap(tmp_path)
    state = load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state.update({
        "status": "needs_revision", "next_phase": None, "user_revision_cycles": 0, "send_backs": 2,
        "plan_reconciliations": [{"at": BASE.isoformat(), "reason": "shot-6 region"}],
        "send_back_history": [{"target_phase": PHASE, "reason": "a"}, {"target_phase": PHASE, "reason": "b"}],
        "phase_telemetry": {PHASE: [{
            "attempt": 1, "started_at": BASE.isoformat(),
            "finished_at": (BASE + timedelta(seconds=OVERRUN)).isoformat(),
            "duration_seconds": OVERRUN, "execution_class": "editorial",
            "outcome": "superseded", "revision_cycle": 0,
        }]},
    })
    workflow._write_state(tmp_path / PROJECT, state)
    return workflow.request_send_back(
        PROJECT, PHASE, reason="user revision", user_directed_revision=True,
        pipeline_dir=tmp_path, now=BASE + timedelta(seconds=OVERRUN + 60),
    )


def test_budgets_still_reset_for_the_new_cycle(tmp_path: Path) -> None:
    state = _revised(tmp_path)
    assert state["send_backs"] == 0 and state["plan_reconciliations"] == []


def test_whole_run_totals_survive_the_reset(tmp_path: Path) -> None:
    state = _revised(tmp_path)
    archive = state["revision_cycle_archive"]
    assert archive[0]["send_backs"] == 2 and len(archive[0]["plan_reconciliations"]) == 1
    totals = workflow._whole_run_totals(state)
    assert totals["send_backs"] == 2
    assert totals["user_directed_revisions"] == 1
    assert totals["plan_reconciliations"] == 1
    assert totals["phases"][PHASE]["slo_exceeded"] is True
    assert totals["phases"][PHASE]["total_seconds"] >= OVERRUN


def test_the_frozen_summary_carries_whole_run_totals(tmp_path: Path) -> None:
    state = _revised(tmp_path)
    workflow._freeze_performance_summary(state, now=BASE + timedelta(seconds=OVERRUN + 120))
    assert state["performance_summary"]["whole_run"]["send_backs"] == 2
