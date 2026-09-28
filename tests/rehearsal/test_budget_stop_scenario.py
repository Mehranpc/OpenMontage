"""#260 scenario 4: budget stop → explicit decision → resume, with the wait accounted.

The recorded first-date run hit the wall budget twice and asked the operator; the wait
for the answer was booked as orchestration gap (#250). Here the rehearsal is driven to
the plan, the budget window is moved back past the wall limit (the only way to spend
45 minutes in a test), and the next front-door command must stop with a decision; the
decision goes through the real `budget-decision` CLI, and the run must then finish
acquisition and region review in the same window.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from scripts.persian_rehearsal import DEFAULT_FIXTURE, PROJECT_ID, Rehearsal


def _age_budget_window(rehearsal: Rehearsal, *, minutes_over: int) -> int:
    path = rehearsal.project / "persian-video-workflow.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    limit = int(state["budgets"]["max_wall_time_minutes"])
    started = datetime.fromisoformat(state["budget_window_started_at"])
    state["budget_window_started_at"] = (started - timedelta(minutes=limit + minutes_over)).isoformat()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return limit


def test_a_budget_stop_is_decided_and_the_run_resumes(tmp_path: Path) -> None:
    rehearsal = Rehearsal(DEFAULT_FIXTURE, tmp_path, echo=False)
    for phase in ("bootstrap", "prepare_inputs", "align", "plan"):
        getattr(rehearsal, phase)()
    limit = _age_budget_window(rehearsal, minutes_over=3)

    request = rehearsal.write("search-request-0.json", rehearsal.decision("search-request-0.json"))
    refusal = rehearsal.wf(
        "asset-search (expect wall budget stop)", "asset-search", PROJECT_ID,
        "--retry-pass", "0", "--request", request, expect_fail=True,
    )
    assert "wall_budget_exceeded" in refusal
    stop = rehearsal.status()["budget_stop"]
    assert stop["reason"] == "wall_budget_exceeded"
    assert stop["threshold_seconds"] == limit * 60
    offered = {option["action"]: option for option in stop["options"]}
    assert set(offered) == {"continue_with_extension", "continue_to_preview", "stop"}
    minimum = int(offered["continue_with_extension"]["minimum_extra_minutes"])
    assert 3 <= minimum <= 5

    state = rehearsal.wf(
        "budget-decision", "budget-decision", PROJECT_ID,
        "--decision", "continue_with_extension", "--extension-minutes", "30",
    )
    assert state["status"] == "active"
    assert "budget_stop" not in state
    assert state["budget_decisions"][-1]["extension_minutes"] == 30
    # #250: the wait for the operator's answer is a human wait, not orchestration gap.
    idle = [span for span in state["causal_telemetry"]["spans"] if span.get("kind") == "human_idle"]
    assert [span["reason"] for span in idle] == ["budget decision: continue_with_extension"]

    rehearsal.acquire()
    rehearsal.regions()
    final = rehearsal.status()
    assert final["status"] == "active"
    assert final["next_phase"] == "no_copy_preflight"
