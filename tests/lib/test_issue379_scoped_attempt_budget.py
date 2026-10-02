from datetime import timedelta

import pytest

from lib import persian_video_workflow as workflow
from tests.lib.test_issue377_region_recovery import _prepared
from tests.lib.test_persian_video_workflow import BASE


def test_accepted_scoped_rewind_admits_real_work_after_prior_retries(tmp_path, monkeypatch):
    project = _prepared(tmp_path, monkeypatch)
    prior = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    prior["attempts"]["acquire_assets"] = 1 + prior["budgets"]["max_revisions_per_stage"]
    workflow._write_state(project, prior)
    rewound = workflow.request_send_back(
        "run", "acquire_assets", reason="reviewed protected-region collision", pipeline_dir=tmp_path, now=BASE,
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION", affected_shot_ids=["shot-1"],
    )
    assert rewound["send_backs"] == 1
    assert rewound["attempts"] == prior["attempts"]
    span = workflow.start_explicit_work_span(
        "run", category="agent_editorial_work", name="prepare affected shot repair", pipeline_dir=tmp_path, now=BASE,
    )
    assert span["phase"] == "acquire_assets"
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["attempts"]["acquire_assets"] == prior["attempts"]["acquire_assets"] + 1
    assert state["asset_reacquisition_scope"]["visualEventIds"] == ["event-1"]


def _rewound_at_limit(tmp_path, monkeypatch):
    project = _prepared(tmp_path, monkeypatch)
    prior = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    ceiling = 1 + prior["budgets"]["max_revisions_per_stage"]
    prior["attempts"]["acquire_assets"] = ceiling
    # Fully spent historical attempts, all predating the accepted grant.
    prior["phase_telemetry"]["acquire_assets"] = [
        {"attempt": n, "started_at": BASE.isoformat(), "finished_at": BASE.isoformat(),
         "duration_seconds": 0, "outcome": "completed", "revision_cycle": 0}
        for n in range(1, ceiling + 1)
    ]
    workflow._write_state(project, prior)
    state = workflow.request_send_back("run", "acquire_assets", reason="collision", pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=1), diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION", affected_shot_ids=["shot-1"])
    return project, prior, state


@pytest.mark.parametrize("legacy", [False, True])
def test_recovery_preserves_history_and_enforces_a_finite_retry_ceiling(tmp_path, monkeypatch, legacy):
    project, prior, state = _rewound_at_limit(tmp_path, monkeypatch)
    if legacy:
        state.pop("phase_attempt_baselines", None)
        workflow._write_state(project, state)
    original_history = list(state["phase_telemetry"]["acquire_assets"])
    limit = 1 + state["budgets"]["max_revisions_per_stage"]
    for index in range(limit):
        state = workflow.record_phase_attempt("run", "acquire_assets", pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=index + 2))
        assert state["attempts"]["acquire_assets"] == prior["attempts"]["acquire_assets"] + index + 1
        assert state["phase_telemetry"]["acquire_assets"][:len(original_history)] == original_history
        assert state["send_backs"] == 1
    before = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="retry budget exhausted"):
        workflow.record_phase_attempt("run", "acquire_assets", pipeline_dir=tmp_path,
            now=BASE + timedelta(seconds=limit + 2))
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path) == before


def test_retry_ceiling_is_not_relaxed_without_an_accepted_rewind(tmp_path, monkeypatch):
    project = _prepared(tmp_path, monkeypatch)
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state["next_phase"] = "acquire_assets"
    state["attempts"]["acquire_assets"] = 1 + state["budgets"]["max_revisions_per_stage"]
    workflow._write_state(project, state)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="retry budget exhausted"):
        workflow.record_phase_attempt("run", "acquire_assets", pipeline_dir=tmp_path, now=BASE)
