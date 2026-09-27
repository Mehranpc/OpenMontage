"""#250: the wait between a budget stop and the operator's decision is human idle.

On the f13d914 run, three human waits happened and telemetry recorded one. The two waits
behind budget questions became orchestration gap, which counted against the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lib.persian_video_workflow import resolve_budget_stop
from tests.lib.test_issue152_revision_budget_decisions import PROJECT, _wall_stopped_run
from tests.lib.test_persian_video_workflow import BASE


def _idle(state: dict) -> list[dict]:
    return [s for s in state["causal_telemetry"]["spans"] if s.get("kind") == "human_idle"]


def test_the_wait_before_an_extension_is_recorded_as_human_idle(tmp_path: Path) -> None:
    limit = _wall_stopped_run(tmp_path)
    state = resolve_budget_stop(
        PROJECT, decision="continue_with_extension", extension_minutes=35, pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=limit + 300 + 240),
    )
    idle = _idle(state)
    assert len(idle) == 1
    assert "budget decision: continue_with_extension" in idle[0]["reason"]
    seconds = (
        datetime.fromisoformat(idle[0]["finished_at"]) - datetime.fromisoformat(idle[0]["started_at"])
    ).total_seconds()
    assert seconds == pytest.approx(240, abs=1)
    run = next(s for s in state["causal_telemetry"]["spans"]
               if s["span_id"] == state["causal_telemetry"]["run_span_id"])
    assert run["outcome"] == "running"


def test_a_stop_decision_records_no_idle_and_stays_terminal(tmp_path: Path) -> None:
    limit = _wall_stopped_run(tmp_path)
    state = resolve_budget_stop(
        PROJECT, decision="stop", pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=limit + 600),
    )
    assert _idle(state) == []
    assert state["status"] == "failed"
