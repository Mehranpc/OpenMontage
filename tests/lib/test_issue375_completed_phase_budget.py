"""Completed phase budgets retain the same parked-time policy as active work."""
from datetime import timedelta
import pytest
from lib import persian_video_workflow as workflow
from tests.lib.test_issue342_parked_time_not_wall_budget import _setup, _commands, BASE
from tests.lib.test_persian_video_workflow import _advance_to, _prepare_inputs_evidence


def _phase(tmp_path, parked, monkeypatch):
    # Input preparation isolates accounting from media contracts; install a
    # controlled 600-second phase SLO, as the budgeted production phases have.
    monkeypatch.setitem(workflow.PHASE_SLO_SECONDS, "prepare_inputs", 600)
    root, _ = _setup(tmp_path)
    state = _advance_to(tmp_path, "prepare_inputs")
    state["budgets"]["max_wall_time_minutes"] = 180
    workflow._write_state(root, state)
    workflow.record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    if parked:
        _commands(root, ("workflow:work-start", 0, 10),
                  ("workflow:work-finish", 7190, 7200))
    else:
        _commands(root, *[("workflow:prepare", t, t + 10) for t in range(0,7200,240)])
    return root, _prepare_inputs_evidence(state)


@pytest.mark.parametrize("parked", [True, False])
def test_public_completion_preserves_parked_policy_and_real_overruns(tmp_path, parked, monkeypatch):
    root, evidence = _phase(tmp_path, parked, monkeypatch)
    result = workflow.complete_phase("run", "prepare_inputs", evidence=evidence,
                                     pipeline_dir=tmp_path, now=BASE+timedelta(seconds=7200))
    assert "prepare_inputs" in result["completed_phases"]
    assert result["next_phase"] == "align_script_timing"
    assert result["phase_telemetry"]["prepare_inputs"][-1]["duration_seconds"] == 7200
    if parked:
        assert result["status"] == "active"
        assert not result.get("budget_stop")
    else:
        assert result["status"] == "failed"
        assert result["budget_stop"]["reason"] == "phase_budget_exceeded"
        assert result["budget_stop"]["observed_seconds"] == 7200


def test_revalidation_releases_legacy_completed_phase_stop_without_grant(tmp_path, monkeypatch):
    root, evidence = _phase(tmp_path, True, monkeypatch)
    with monkeypatch.context() as old:
        old.setattr(workflow, "parked_wall_seconds", lambda *a, **kw: {"parked_seconds":0})
        before = workflow.complete_phase("run", "prepare_inputs", evidence=evidence,
                                         pipeline_dir=tmp_path, now=BASE+timedelta(seconds=7200))
    assert before["budget_stop"]["reason"] == "phase_budget_exceeded"
    after = workflow.revalidate_budget_stop("run", pipeline_dir=tmp_path,
                                           now=BASE+timedelta(hours=4))
    assert after["status"] == "active"
    assert not after.get("budget_stop")
    assert after["budget_stop_revalidations"][-1]["outcome"] == "released"
    for key in ("budgets", "budget_decisions", "budget_window_started_at", "attempts",
                "send_backs", "completed_phases", "next_phase", "phase_telemetry"):
        assert after.get(key) == before.get(key)
    assert workflow.revalidate_budget_stop("run", pipeline_dir=tmp_path,
            now=BASE+timedelta(hours=5)) == after


def test_later_parked_wait_cannot_release_a_real_completed_phase_overrun(tmp_path, monkeypatch):
    root, evidence = _phase(tmp_path, False, monkeypatch)
    before = workflow.complete_phase("run", "prepare_inputs", evidence=evidence,
                                     pipeline_dir=tmp_path, now=BASE+timedelta(seconds=7200))
    assert before["budget_stop"]["observed_seconds"] == 7200
    after = workflow.revalidate_budget_stop("run", pipeline_dir=tmp_path,
                                           now=BASE+timedelta(hours=4))
    assert after["status"] == "failed"
    assert after["budget_stop"] == before["budget_stop"]
    assert after["budget_stop_revalidations"][-1]["current_stop"]["observed_seconds"] == 7200
    assert after["budget_stop_revalidations"][-1]["outcome"] == "still_exceeded"
