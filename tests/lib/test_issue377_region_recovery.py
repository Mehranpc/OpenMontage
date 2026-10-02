import json

import pytest

from lib import persian_region_commands as regions
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_region_commands import _project, _fake_ffmpeg, _annotations
from tests.lib.test_persian_video_workflow import _bootstrap, _advance_to, BASE


def _prepared(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "review_subject_regions")
    project = _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    regions.build_sheets(tmp_path, "run")
    annotations = _annotations()
    for frame in annotations["shots"][0]["frames"]:
        frame.clear()
    for position, frame in zip(["start", "middle", "end"], annotations["shots"][0]["frames"]):
        frame.update({"position": position, "priority": "hard", "grid": {"x1": 0, "y1": 0, "x2": 10, "y2": 10}})
    proposal = regions.propose_regions(tmp_path, "run", annotations)
    assert proposal["openingHookPlacement"]["feasible"] is False
    assert not (project / "artifacts/edit_decisions.json").exists()
    return project


def test_public_scoped_recovery_before_edit_uses_current_region_evidence(tmp_path, monkeypatch):
    project = _prepared(tmp_path, monkeypatch)
    preserved = (project / "artifacts/asset_manifest.json").read_bytes()
    state = workflow.request_send_back(
        "run", "acquire_assets", pipeline_dir=tmp_path, now=BASE,
        reason="Opening hook is blocked by reviewed protected subject",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION", affected_shot_ids=["shot-1"],
    )
    assert state["next_phase"] == "acquire_assets"
    assert state["send_backs"] == 1
    assert state["asset_reacquisition_scope"]["shotIds"] == ["shot-1"]
    assert state["asset_reacquisition_scope"]["visualEventIds"] == ["event-1"]
    assert (project / "artifacts/asset_manifest.json").read_bytes() == preserved
    assert not (project / "artifacts/edit_decisions.json").exists()


@pytest.mark.parametrize("mutation", ["scene", "manifest", "proposal", "sheet", "unaffected", "wrong_code", "edit_override"])
def test_region_recovery_refuses_unbound_or_out_of_scope_requests(tmp_path, monkeypatch, mutation):
    project = _prepared(tmp_path, monkeypatch)
    kwargs = {"diagnostic_code": "ASSET_SELECTION_HARD_REGION_COLLISION", "affected_shot_ids": ["shot-1"]}
    if mutation in {"scene", "manifest"}:
        path = project / "artifacts" / ("scene_plan.json" if mutation == "scene" else "asset_manifest.json")
        payload = json.loads(path.read_text())
        if mutation == "scene":
            payload["beats"][0]["duration_seconds"] = 5.0
        else:
            payload["assets"][1]["source_in_seconds"] = 2.0
        path.write_text(json.dumps(payload))
    elif mutation == "proposal":
        path = project / regions.SHEET_DIR / regions.PROPOSAL_NAME
        payload = json.loads(path.read_text()); payload["source"]["indexFingerprint"] = "a" * 64
        path.write_text(json.dumps(payload))
    elif mutation == "sheet":
        (project / regions.SHEET_DIR / "shot-001-start.png").write_bytes(b"corrupt")
    elif mutation == "unaffected":
        kwargs["affected_shot_ids"] = ["shot-2"]
    elif mutation == "wrong_code":
        kwargs["diagnostic_code"] = "FILM_TYPE_LAYOUT"
    else:
        kwargs["edit_draft_json"] = str(project / "artifacts/edit_decisions.json")
    before = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError):
        workflow.request_send_back("run", "acquire_assets", reason="repair", pipeline_dir=tmp_path, now=BASE, **kwargs)
    after = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    assert after == before


def test_region_recovery_keeps_local_first_reuse_and_sendback_ceiling(tmp_path, monkeypatch):
    project = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(workflow, "asset_workspace_status", lambda _: {
        "selectedCandidateIds": {"event-1": "selected"},
        "reusableCandidatesByVisualEvent": {"event-1": [
            {"candidateId": "selected", "identity": {"sourceId": "one"}},
            {"candidateId": "alternate", "identity": {"sourceId": "two"}},
        ]},
    })
    before = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="existing reviewed asset option remains"):
        workflow.request_send_back("run", "acquire_assets", reason="repair", pipeline_dir=tmp_path, now=BASE,
            diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION", affected_shot_ids=["shot-1"])
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path) == before
    monkeypatch.setattr(workflow, "asset_workspace_status", lambda _: {})
    before["send_backs"] = before["budgets"]["max_send_backs"]
    workflow._write_state(project, before)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="send-back budget exhausted"):
        workflow.request_send_back("run", "acquire_assets", reason="repair", pipeline_dir=tmp_path, now=BASE,
            diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION", affected_shot_ids=["shot-1"])
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path) == before
