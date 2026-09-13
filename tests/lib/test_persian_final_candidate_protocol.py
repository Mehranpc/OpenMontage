import hashlib
import json
from pathlib import Path

import pytest
import yaml

from lib.checkpoint import (
    CheckpointValidationError,
    _validate_persian_compose_lifecycle,
    init_project,
    write_checkpoint,
)
from lib.persian_preflight import (NoCopyPersianCompose, extract_edit_decisions, preflight_edit_decisions, summarize)
from schemas.artifacts import validate_artifact

ROOT = Path(__file__).resolve().parents[2]


def _make_candidate(tmp_path: Path, name: str = "candidate.mp4", data: bytes = b"candidate") -> tuple[Path, str]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def _report(
    path: Path,
    status: str,
    approved: bool,
    verified: bool,
    *,
    digest: str | None = None,
    include_digest: bool = True,
) -> dict:
    output = {
        "path": str(path),
        "format": "mp4",
        "resolution": "1080x1920",
        "duration_seconds": 10,
    }
    if include_digest:
        output["sha256"] = digest or hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "version": "1.0",
        "outputs": [output],
        "delivery_status": status,
        "human_visual_approval": approved,
        "persian_text_verified": verified,
    }


def _prior_checkpoint(report: dict) -> dict:
    return {
        "version": "1.0",
        "project_id": "run",
        "pipeline_type": "persian-footage",
        "stage": "compose",
        "status": "awaiting_human",
        "timestamp": "2026-09-09T21:00:00+00:00",
        "checkpoint_policy": "guided",
        "human_approval_required": True,
        "human_approved": False,
        "artifacts": {"render_report": report},
    }


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
    candidate, _ = _make_candidate(tmp_path)
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="GATE VIOLATION"):
        write_checkpoint(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(candidate, "approved", True, True)},
            pipeline_type="persian-footage",
        )


def test_compose_cannot_self_approve_without_candidate_transition(tmp_path):
    candidate, digest = _make_candidate(tmp_path)
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    with pytest.raises(CheckpointValidationError, match="APPROVAL TRANSITION"):
        write_checkpoint(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(candidate, "approved", True, True)},
            pipeline_type="persian-footage", human_approved=True,
            metadata={"approval_record": {
                "source": "explicit_user_response",
                "candidate_path": str(candidate),
                "candidate_sha256": digest,
            }},
        )


def test_candidate_requires_sha_and_matching_file_bytes(tmp_path):
    candidate, _ = _make_candidate(tmp_path)
    with pytest.raises(CheckpointValidationError, match="64-character sha256"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "awaiting_human",
            {"render_report": _report(
                candidate, "final_candidate", False, False, include_digest=False
            )},
            False, None,
        )
    with pytest.raises(CheckpointValidationError, match="does not match the exact file bytes"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "awaiting_human",
            {"render_report": _report(
                candidate, "final_candidate", False, False, digest="b" * 64
            )},
            False, None,
        )


def test_approval_is_bound_to_prior_candidate_path_digest_and_bytes(tmp_path):
    project = tmp_path / "run"
    project.mkdir()
    candidate, digest = _make_candidate(project / "renders")
    candidate_report = _report(candidate, "final_candidate", False, False)
    _validate_persian_compose_lifecycle(
        tmp_path, "run", "compose", "awaiting_human",
        {"render_report": candidate_report}, False, None,
    )
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_prior_checkpoint(candidate_report)), encoding="utf-8"
    )
    metadata = {"approval_record": {
        "source": "explicit_user_response",
        "candidate_path": str(candidate),
        "candidate_sha256": digest,
    }}
    approved_report = _report(candidate, "approved", True, True)
    _validate_persian_compose_lifecycle(
        tmp_path, "run", "compose", "completed",
        {"render_report": approved_report}, True, metadata,
    )

    alternate, alternate_digest = _make_candidate(
        project / "renders", "alternate.mp4", b"alternate"
    )
    with pytest.raises(CheckpointValidationError, match="path or sha256 changed"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(alternate, "approved", True, True)}, True,
            {"approval_record": {
                "source": "explicit_user_response",
                "candidate_path": str(alternate),
                "candidate_sha256": alternate_digest,
            }},
        )

    candidate.write_bytes(b"overwritten after review")
    with pytest.raises(CheckpointValidationError, match="does not match the exact file bytes"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "completed",
            {"render_report": approved_report}, True, metadata,
        )


def test_completion_requires_explicit_user_approval_record(tmp_path):
    project = tmp_path / "run"
    project.mkdir()
    candidate, digest = _make_candidate(project / "renders")
    candidate_report = _report(candidate, "final_candidate", False, False)
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_prior_checkpoint(candidate_report)), encoding="utf-8"
    )
    with pytest.raises(CheckpointValidationError, match="APPROVAL PROVENANCE"):
        _validate_persian_compose_lifecycle(
            tmp_path, "run", "compose", "completed",
            {"render_report": _report(candidate, "approved", True, True)}, True,
            {"approval_record": {
                "source": "continuation_goal",
                "candidate_path": str(candidate),
                "candidate_sha256": digest,
            }},
        )


def test_candidate_report_schema(tmp_path):
    candidate, _ = _make_candidate(tmp_path)
    validate_artifact(
        "render_report", _report(candidate, "final_candidate", False, False)
    )


def test_no_copy_stage_and_helpers(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    staging = tmp_path / "stage"
    assert NoCopyPersianCompose._stage(source, staging, "x") == str(source)
    assert not staging.exists()
    artifact = {"persian": {"shots": [], "moments": []}}
    assert extract_edit_decisions({"artifacts": {"edit_decisions": artifact}}) is artifact
    result = summarize({
        "design": {"resolved": {"layoutVersion": 12}},
        "moments": [{
            "id": "m1",
            "layoutGeometry": {
                "x": .1, "y": .2, "w": .3, "h": .4,
                "placement": "upper-left",
            },
        }],
        "watermarkPlan": [],
    }, [])
    assert result["mediaCopies"] == 0
    assert result["moments"][0]["rect"] == {
        "x": .1, "y": .2, "w": .3, "h": .4,
    }
    assert result["moments"][0]["geometry"]["placement"] == "upper-left"


def test_preflight_refuses_a_weak_single_event_opening_before_render_work():
    payload = {
        "persian": {
            "durationSeconds": 12.0,
            "shots": [{"id": "s1", "startSeconds": 0.0, "endSeconds": 12.0}],
            "moments": [],
            "typographicBeats": [],
        }
    }
    with pytest.raises(ValueError, match="first 3 seconds"):
        preflight_edit_decisions(payload)


def test_summary_can_carry_retention_audit_without_media_copies():
    retention = {"problems": [], "first3Seconds": {"eventCount": 2}}
    result = summarize({"moments": [], "watermarkPlan": []}, [], retention)
    assert result["retentionAudit"] is retention
    assert result["mediaCopies"] == 0


def test_summary_reports_film_type_213_opening_caption_and_watermark_evidence():
    props = {
        "format": "vertical", "durationSeconds": 40.0, "captionMode": "hybrid",
        "design": {
            "profileVersion": "2.13.0",
            "resolved": {
                "layoutVersion": 13,
                "formats": {"vertical": {"safeArea": {"top": .14, "bottom": .35, "left": .08, "right": .16}}},
                "watermark": {
                    "introDelaySeconds": 5, "minCoverageRatio": .7, "targetCoverageRatio": .8,
                    "minDwellSeconds": 6, "maxRelocations": 5,
                    "longFormThresholdSeconds": 30, "minLongFormRelocations": 2,
                },
            },
        },
        "shots": [{
            "id": "s1", "narrativeRole": "hook", "startSeconds": 0.0, "endSeconds": 4.0,
            "semanticRole": "reward_problem_hook", "semanticDirection": "child_resistance",
            "openingSemanticMatch": True, "selectionReason": "کودک در حضور والد مقاومت می‌کند",
            "showsSubject": True, "humanPresence": True,
        }],
        "moments": [{
            "id": "m1", "kind": "hook", "purpose": "hook-pattern-interrupt",
            "segments": [{"role": "hero", "text": "به هر کار خوبی"}, {"role": "tail", "text": "جایزه می‌دی؟"}],
        }],
        "captions": [{
            "id": "c1", "text": "این یک کپشن سالم است.", "startSeconds": 0.0, "endSeconds": 2.0,
        }],
        "watermarkPlan": [
            {"zone": "lower-left", "startSeconds": 5.0, "endSeconds": 20.0},
            {"zone": "lower-right", "startSeconds": 20.0, "endSeconds": 40.0},
        ],
    }
    result = summarize(props, [])
    assert result["openingSemanticMatch"] is True
    assert result["openingHookTokenCount"] >= 3
    assert result["openingHookSingleTokenFallback"] is False
    assert result["captionBandCenterX"] == .5
    assert result["captionBandSymmetric"] is True
    assert result["subtitleHardBoundariesPassed"] is True
    watermark = result["watermarkEvidence"]
    assert watermark["noEarlyWatermark"] is True
    assert watermark["coverageRatio"] == .875
    assert watermark["coverageFloorPassed"] is True
    assert watermark["coverageTargetReached"] is True
    assert watermark["relocationCount"] == 1
    assert watermark["relocationTarget"] == 2
    assert watermark["relocationTargetReached"] is False
    assert watermark["distinctZones"] == ["lower-left", "lower-right"]
    assert watermark["distinctZoneCount"] == 2


def test_summary_detects_caption_hard_boundary_crossing():
    props = {
        "format": "vertical", "durationSeconds": 10.0, "captionMode": "hybrid",
        "design": {"profileVersion": "2.13.0", "resolved": {
            "formats": {"vertical": {"safeArea": {"top": .14, "bottom": .35, "left": .08, "right": .16}}},
            "watermark": {},
        }},
        "moments": [], "shots": [], "watermarkPlan": [],
        "captions": [{"id": "c1", "text": "تمام شد. جملهٔ بعد", "startSeconds": 0.0, "endSeconds": 2.0}],
    }
    result = summarize(props, [])
    assert result["subtitleHardBoundariesPassed"] is False
    assert result["subtitleHardBoundaryProblems"]


def test_protocol_is_required_and_bounded():
    manifest = (ROOT / "pipeline_defs/persian-footage.yaml").read_text()
    protocol = (ROOT / "skills/pipelines/persian-footage/final-candidate-protocol.md").read_text()
    assert "pipelines/persian-footage/final-candidate-protocol" in manifest
    assert "Never call `PersianCompose._build_props` directly" in protocol
    assert "three footage/layout candidates per beat" in protocol
    assert "candidate_sha256" in protocol
    assert "recomputes it" in protocol
