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
