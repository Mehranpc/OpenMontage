from pathlib import Path
import pytest
import yaml
from lib.checkpoint import CheckpointValidationError, init_project, write_checkpoint
from lib.persian_preflight import NoCopyPersianCompose, extract_edit_decisions, summarize
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]


def test_one_post_render_gate():
    data = yaml.safe_load((ROOT / "pipeline_defs/persian-footage.yaml").read_text())
    gates = {s["name"]: s["human_approval_default"] for s in data["stages"]}
    assert gates == {"idea": False, "script": False, "scene_plan": False,
                     "assets": False, "edit": False, "compose": True}


def test_precompose_cannot_claim_approval(tmp_path):
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="APPROVAL PROVENANCE"):
        write_checkpoint(tmp_path, "run", "edit", "in_progress", {},
                         pipeline_type="persian-footage", human_approved=True)


def test_compose_completion_requires_approval(tmp_path):
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(tmp_path, "run", "compose", "completed", {},
                         pipeline_type="persian-footage")


def test_candidate_report_schema():
    validate_artifact("render_report", {"version": "1.0", "outputs": [{
        "path": "candidate.mp4", "format": "mp4", "resolution": "1080x1920",
        "duration_seconds": 10}], "delivery_status": "final_candidate",
        "human_visual_approval": False, "persian_text_verified": False})


def test_no_copy_stage_and_helpers(tmp_path):
    source = tmp_path / "clip.mp4"; source.write_bytes(b"x")
    staging = tmp_path / "stage"
    assert NoCopyPersianCompose._stage(source, staging, "x") == str(source)
    assert not staging.exists()
    artifact = {"persian": {"shots": [], "moments": []}}
    assert extract_edit_decisions({"artifacts": {"edit_decisions": artifact}}) is artifact
    result = summarize({"design": {"resolved": {"layoutVersion": 12}},
                        "moments": [], "watermarkPlan": []}, [])
    assert result["mediaCopies"] == 0


def test_protocol_is_required_and_bounded():
    manifest = (ROOT / "pipeline_defs/persian-footage.yaml").read_text()
    protocol = (ROOT / "skills/pipelines/persian-footage/final-candidate-protocol.md").read_text()
    assert "pipelines/persian-footage/final-candidate-protocol" in manifest
    assert "Never call `PersianCompose._build_props` directly" in protocol
    assert "three footage/layout candidates per beat" in protocol
