"""#358: strict new frame reviews and immutable legacy manifest recovery."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from lib import persian_asset_commands as commands
from lib import persian_asset_workspace as workspace
from schemas.artifacts import validate_artifact
from tests.lib.test_issue35_asset_candidate_workspace import (
    _discovered, _review, _selected_candidate, _stage, _write_matching_scene_plan,
)


@pytest.mark.parametrize("extra", [
    {"face_visible": False},
    {"unknown_evidence": True},
    {"at_3_seconds": "yes"},
    {"subject_grid": {"start": {}, "middle": {}, "end": {}, "other": {}}},
])
def test_new_invalid_frame_review_is_refused_without_persisting(tmp_path: Path, extra: dict) -> None:
    project = tmp_path / "run"
    discovery = workspace.record_discovery_pass(project, 0, [_discovered(project)])
    candidate = _stage(project, discovery["candidateIds"][0])
    path = workspace._candidate_path(project, candidate["candidateId"])
    before = path.read_bytes()
    review = _review()
    review["frame_review"].update(extra)
    with pytest.raises(workspace.PersianAssetWorkspaceError, match="frame_review"):
        workspace.record_candidate_review(project, candidate["candidateId"], review)
    assert path.read_bytes() == before
    assert not workspace.load_asset_candidate(project, candidate["candidateId"]).get("reviewSha256")


@pytest.mark.parametrize("face_visible", [False, True])
def test_legacy_face_annotation_builds_and_audits_without_rewriting_evidence(
    tmp_path: Path, face_visible: bool,
) -> None:
    project = tmp_path / "run"
    staged, _ = _selected_candidate(project)
    _write_matching_scene_plan(project)
    path = workspace._candidate_path(project, staged["candidateId"])
    candidate = json.loads(path.read_text())
    # Represent a record written by the old review admission code, not a migration.
    candidate["review"]["frame_review"]["face_visible"] = face_visible
    candidate["reviewSha256"] = workspace._sha256({
        "candidateIdentitySha256": candidate["identitySha256"],
        "candidateContext": candidate.get("context") or {},
        "review": candidate["review"],
    })
    workspace._atomic_json(path, candidate)
    selections = workspace._read_selections(project)
    selections["event-1"]["reviewSha256"] = candidate["reviewSha256"]
    workspace._write_selections(project, selections)
    before = path.read_bytes()
    selections_before = workspace._selections_path(project).read_bytes()

    result = commands.build_manifest(tmp_path, "run")
    manifest_path = Path(result["manifestPath"])
    manifest_before = manifest_path.read_bytes()
    manifest = json.loads(manifest_before)
    validate_artifact("asset_manifest", manifest)
    row = manifest["assets"][0]
    expected_frame = deepcopy(candidate["review"]["frame_review"])
    expected_frame.pop("face_visible")
    assert row["frame_review"] == expected_frame
    assert row["asset_review_sha256"] == candidate["reviewSha256"]
    assert row["asset_candidate_identity_sha256"] == candidate["identitySha256"]
    assert workspace.validate_asset_manifest_against_workspace(project, manifest)["selectedCount"] == 1
    assert commands.build_manifest(tmp_path, "run")["idempotent"] is True
    assert manifest_path.read_bytes() == manifest_before
    selected = workspace.select_asset_candidate(
        project, "event-1", staged["candidateId"], rejected_alternatives={},
    )
    assert selected["idempotent"] is True
    assert selected["manifestEvidence"]["frame_review"] == expected_frame
    assert path.read_bytes() == before
    assert workspace._selections_path(project).read_bytes() == selections_before

    modified = deepcopy(candidate["review"])
    modified["frame_review"].pop("face_visible")
    with pytest.raises(workspace.PersianAssetWorkspaceError, match="immutable"):
        workspace.record_candidate_review(project, staged["candidateId"], modified)
    altered = deepcopy(manifest)
    altered["assets"][0]["frame_review"]["observed"] = "unreviewed claim"
    with pytest.raises(workspace.PersianAssetWorkspaceError, match="frame_review"):
        workspace.validate_asset_manifest_against_workspace(project, altered)
    assert path.read_bytes() == before


@pytest.mark.parametrize("extra", [{"unknown_evidence": True}, {"face_visible": "false"}])
def test_legacy_projection_does_not_silently_drop_unknown_or_malformed_evidence(extra: dict) -> None:
    review = _review()
    review["frame_review"].update(extra)
    with pytest.raises(workspace.PersianAssetWorkspaceError, match="frame_review"):
        workspace._manifest_evidence({"review": review})


def test_all_canonical_optional_frame_fields_survive_projection() -> None:
    frame = {
        "start": True, "middle": True, "end": True, "observed": "measured frames",
        "midpoint_before_1_5": True, "at_3_seconds": False,
        "placement_space": "centre_band",
        "subject_grid": {"start": {}, "middle": {}, "end": {}},
    }
    assert workspace._validate_review({**_review(), "frame_review": frame})["frame_review"] == frame
    assert workspace._manifest_evidence({"review": {"frame_review": frame}})["frame_review"] == frame


@pytest.mark.parametrize("extra", [
    {"unknown_evidence": True}, {"face_visible": "false"}, {"at_3_seconds": "yes"},
])
def test_invalid_legacy_evidence_cannot_partially_commit_a_selection(tmp_path: Path, extra: dict) -> None:
    project = tmp_path / "run"
    discovery = workspace.record_discovery_pass(project, 0, [_discovered(project)])
    staged = _stage(project, discovery["candidateIds"][0])
    workspace.record_candidate_review(project, staged["candidateId"], _review())
    path = workspace._candidate_path(project, staged["candidateId"])
    candidate = json.loads(path.read_text())
    candidate["review"]["frame_review"].update(extra)
    candidate["reviewSha256"] = workspace._sha256({
        "candidateIdentitySha256": candidate["identitySha256"],
        "candidateContext": candidate.get("context") or {},
        "review": candidate["review"],
    })
    workspace._atomic_json(path, candidate)
    before = path.read_bytes()
    with pytest.raises(workspace.PersianAssetWorkspaceError, match="frame_review"):
        workspace.select_asset_candidate(
            project, "event-1", staged["candidateId"], rejected_alternatives={},
        )
    assert not workspace._selections_path(project).exists()
    assert path.read_bytes() == before
