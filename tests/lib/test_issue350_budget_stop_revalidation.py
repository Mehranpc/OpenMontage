"""#350: accounting recovery does not buy a stale extension or bypass real work."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from tests.lib.test_issue342_parked_time_not_wall_budget import _setup, _commands, BASE


@pytest.mark.parametrize("parked", [True, False])
def test_revalidate_stop_preserves_real_budgets_and_reopens_only_stale_stop(
    tmp_path: Path, monkeypatch, parked: bool,
) -> None:
    root, limit = _setup(tmp_path)
    stopped = BASE + timedelta(seconds=7200)
    if parked:
        _commands(root, ("workflow:asset-search", 0, 10),
                  ("workflow:asset-candidate-stage", 7190, 7200))
    else:
        _commands(root, *[
            ("workflow:asset-candidate-review", t, t + 10)
            for t in range(0, 7200, 240)
        ])
    # The old oracle charged raw elapsed time. Restore the corrected production
    # accounting before exercising the public recovery boundary.
    with monkeypatch.context() as old:
        old.setattr(workflow, "parked_wall_seconds",
                    lambda *a, **kw: {"parked_seconds": 0})
        with pytest.raises(workflow.PersianVideoWorkflowError, match="wall_budget_exceeded"):
            workflow.enforce_front_door_budget(
                "run", operation="workflow:work-start", pipeline_dir=tmp_path, now=stopped,
            )
    before = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    original_stop = before["budget_stop"]
    now = stopped + timedelta(hours=4)
    after = workflow.revalidate_budget_stop("run", pipeline_dir=tmp_path, now=now)
    assert after["budget_window_started_at"] == before["budget_window_started_at"]
    for key in ("budgets", "budget_decisions", "send_backs", "phase_attempts", "next_phase"):
        assert after.get(key) == before.get(key)
    audit = after["budget_stop_revalidations"][-1]
    assert audit["original_stop"] == original_stop
    assert audit["revalidated_at"] == now.isoformat()
    if parked:
        assert after["status"] == "active"
        assert not after.get("budget_stop")
        assert audit["outcome"] == "released"
        workflow.enforce_front_door_budget(
            "run", operation="workflow:work-start", pipeline_dir=tmp_path, now=now,
        )
        status = workflow.workflow_status("run", pipeline_dir=tmp_path, now=now)
        assert status["operational_summary"]["charged_wall_seconds"] < limit
        assert workflow.revalidate_budget_stop(
            "run", pipeline_dir=tmp_path, now=now
        ) == after
        span = workflow.start_explicit_work_span(
            "run", category="agent_editorial_work", name="new work",
            pipeline_dir=tmp_path, now=now,
        )
        assert span["kind"] == "explicit_work"
    else:
        assert after["status"] == "failed"
        assert after["budget_stop"] == original_stop
        assert audit["outcome"] == "still_exceeded"
        assert audit["current_stop"]["reason"] == "wall_budget_exceeded"


def test_revalidation_checks_phase_budget_even_when_wall_stop_was_stale(
    tmp_path: Path, monkeypatch,
) -> None:
    root, _ = _setup(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state["next_phase"] = "no_copy_preflight"
    state["budgets"]["max_wall_time_minutes"] = 180
    workflow._write_state(root, state)
    workflow.record_phase_attempt(
        "run", "no_copy_preflight", pipeline_dir=tmp_path, now=BASE,
    )
    _commands(root, *[
        ("workflow:asset-candidate-review", t, t + 10)
        for t in range(0, 7200, 240)
    ])
    with pytest.raises(workflow.PersianVideoWorkflowError, match="phase_budget_exceeded"):
        workflow.enforce_front_door_budget(
            "run", operation="workflow:work-start", pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=7200),
        )
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state["budget_stop"]["reason"] = "wall_budget_exceeded"
    workflow._write_state(root, state)
    result = workflow.revalidate_budget_stop(
        "run", pipeline_dir=tmp_path, now=BASE + timedelta(hours=3),
    )
    assert result["status"] == "failed"
    assert result["budget_stop_revalidations"][-1]["current_stop"]["reason"] == "phase_budget_exceeded"


def test_budget_revalidation_cli_is_exempt_from_the_stop_guard(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(workflow, "revalidate_budget_stop",
                        lambda project_id: called.append(project_id) or {"status": "active"})
    monkeypatch.setattr(workflow, "enforce_front_door_budget",
                        lambda *a, **kw: pytest.fail("recovery blocked by its own stop"))
    monkeypatch.setattr(workflow, "record_cli_command_edge", lambda *a, **kw: None)
    assert workflow.main(["budget-revalidate", "run"]) == 0
    assert called == ["run"]
