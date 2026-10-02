import json

from lib import persian_region_commands as regions
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_region_commands import _project, _fake_ffmpeg, _annotations
from tests.lib.test_persian_video_workflow import _bootstrap, _advance_to, BASE


def test_public_scoped_recovery_before_edit_uses_current_region_evidence(tmp_path, monkeypatch):
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
