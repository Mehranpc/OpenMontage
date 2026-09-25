from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from lib import persian_asset_workspace as assets
from lib import persian_edit_workspace as edits
from lib.persian_edit_workspace import PersianEditWorkspaceError
from tests.fixture_support.p4_failed_shadow import load_issue138_fixture
from tests.lib.test_issue35_asset_candidate_workspace import _discovered, _review, _stage
from tests.lib.test_issue35_convergence_workspace import _edit


def _reviewed_window(project: Path, *, start: float, duration: float) -> dict:
    discovery_ids = assets.record_discovery_pass(
        project, 0, [_discovered(project, source_id="6115070", duration=30.0)]
    )["candidateIds"]
    candidate = _stage(
        project, discovery_ids[0], event="event-1", start=start, duration=duration
    )
    assets.record_candidate_review(project, candidate["candidateId"], _review())
    return assets.load_asset_candidate(project, candidate["candidateId"])


def _edit_for_candidate(candidate: dict, *, source_start: float, duration: float) -> dict:
    edit = _edit()
    edit["persian"]["durationSeconds"] = duration
    shot = edit["persian"]["shots"][0]
    shot.pop("src", None)
    shot["source"] = candidate["source"]["path"]
    shot["startSeconds"] = 0.0
    shot["endSeconds"] = duration
    shot["sourceInSeconds"] = source_start
    return edit


def _binding(candidate_id: str) -> dict:
    return {
        "version": "1.0",
        "shotBindings": [{"shotId": "shot-1", "candidateId": candidate_id}],
    }


def _persist_passing_report(project: Path, attempt_id: str) -> None:
    candidate = edits.load_convergence_candidate(project, attempt_id)
    draft = project / ".drafts" / "edit" / attempt_id / "edit_decisions.json"
    payload = json.loads(draft.read_text(encoding="utf-8"))
    report = project / ".preflight" / "edit" / attempt_id / "preflight_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps({
            "ok": True,
            "artifactSha256": edits.artifact_sha256(payload),
            "dependencyDigests": candidate["dependencyDigests"],
        }),
        encoding="utf-8",
    )


def test_issue138_unreviewed_window_is_refused_before_candidate_consumption(tmp_path: Path) -> None:
    fixture = load_issue138_fixture()
    observed = fixture["cases"]["F3"]
    assert observed["observed"]["attemptedWindowWasReviewed"] is False
    reviewed_window = observed["observed"]["workspaceReviewedWindow"]
    attempted_window = observed["input"]["attemptedEditIdentity"]["sourceWindow"]

    project = tmp_path / "project"
    duration = reviewed_window["endSeconds"] - reviewed_window["startSeconds"]
    reviewed = _reviewed_window(
        project, start=reviewed_window["startSeconds"], duration=duration
    )
    base = _edit_for_candidate(
        reviewed, source_start=reviewed_window["startSeconds"], duration=duration
    )
    edits.stage_edit_draft(project, "base", base, max_candidates=10)

    child = deepcopy(base)
    child["persian"]["shots"][0]["sourceInSeconds"] = attempted_window["startSeconds"]
    before = edits.convergence_status(project)["candidateCount"]
    with pytest.raises(PersianEditWorkspaceError, match="source window is absent"):
        edits.stage_edit_draft(
            project,
            "f3-unreviewed",
            child,
            parent_attempt_id="base",
            diagnostic_issue={"code": "ASSET_SELECTION_HARD_REGION_COLLISION", "recoveryClass": "ASSET_SELECTION"},
            strategy="reuse_reviewed_non_overlapping_source_window",
            changed_fields=["assets.selection"],
            max_candidates=10,
            asset_binding_request=_binding(reviewed["candidateId"]),
            enforce_asset_bindings=True,
        )
    assert edits.convergence_status(project)["candidateCount"] == before


def test_asset_recovery_requires_explicit_reviewed_binding_before_candidate_count(tmp_path: Path) -> None:
    project = tmp_path / "project"
    reviewed = _reviewed_window(project, start=0.0, duration=6.0)
    base = _edit_for_candidate(reviewed, source_start=0.0, duration=6.0)
    edits.stage_edit_draft(project, "base", base, max_candidates=10)
    child = deepcopy(base)
    child["persian"]["shots"][0]["sourceInSeconds"] = 6.0
    before = edits.convergence_status(project)["candidateCount"]
    with pytest.raises(PersianEditWorkspaceError, match="requires exact reviewed asset-workspace bindings"):
        edits.stage_edit_draft(
            project,
            "missing-binding",
            child,
            parent_attempt_id="base",
            diagnostic_issue={"code": "ASSET_SELECTION_HARD_REGION_COLLISION", "recoveryClass": "ASSET_SELECTION"},
            strategy="reuse_reviewed_non_overlapping_source_window",
            changed_fields=["assets.selection"],
            max_candidates=10,
            enforce_asset_bindings=True,
        )
    assert edits.convergence_status(project)["candidateCount"] == before


def test_exact_reviewed_binding_is_immutable_and_promotion_requires_manifest_rebind(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_id = assets.record_discovery_pass(
        project, 0, [_discovered(project, source_id="6115070", duration=30.0)]
    )["candidateIds"][0]
    old_stage = _stage(project, discovery_id, event="event-1", start=0.0, duration=6.0, rank=1)
    new_stage = _stage(project, discovery_id, event="event-1", start=6.0, duration=6.0, rank=2)
    for item in (old_stage, new_stage):
        assets.record_candidate_review(project, item["candidateId"], _review())
    old = assets.load_asset_candidate(project, old_stage["candidateId"])
    new = assets.load_asset_candidate(project, new_stage["candidateId"])

    base = _edit_for_candidate(old, source_start=0.0, duration=6.0)
    edits.stage_edit_draft(project, "base", base, max_candidates=10)
    child = _edit_for_candidate(new, source_start=6.0, duration=6.0)
    staged = edits.stage_edit_draft(
        project,
        "bound-new-window",
        child,
        parent_attempt_id="base",
        diagnostic_issue={"code": "ASSET_SELECTION_HARD_REGION_COLLISION", "recoveryClass": "ASSET_SELECTION"},
        strategy="reuse_reviewed_non_overlapping_source_window",
        changed_fields=["assets.selection"],
        max_candidates=10,
        asset_binding_request=_binding(new["candidateId"]),
        enforce_asset_bindings=True,
    )
    manifest = edits.load_convergence_candidate(project, "bound-new-window")
    assert staged["changedScopes"] == ["assets"]
    assert manifest["assetBindings"][0]["candidateId"] == new["candidateId"]
    assert manifest["assetBindings"][0]["manifestBinding"]["intended_crop"]["mode"] == "cover"
    _persist_passing_report(project, "bound-new-window")

    assets.select_asset_candidate(
        project, "event-1", old["candidateId"],
        rejected_alternatives={new["candidateId"]: "Keep the old window for mismatch fixture."},
    )
    artifacts = project / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "asset_manifest.json").write_text(
        json.dumps(assets.build_asset_manifest_from_workspace(project)), encoding="utf-8"
    )
    with pytest.raises(PersianEditWorkspaceError, match="does not match edit-bound"):
        edits.promote_edit_draft(project, "bound-new-window")

    assets.select_asset_candidate(
        project, "event-1", new["candidateId"],
        rejected_alternatives={old["candidateId"]: "Use the reviewed recovery window."},
        replace_existing=True,
    )
    (artifacts / "asset_manifest.json").write_text(
        json.dumps(assets.build_asset_manifest_from_workspace(project)), encoding="utf-8"
    )
    promoted = edits.promote_edit_draft(project, "bound-new-window")
    assert promoted["promoted"] is True


def test_edit_stage_parser_exposes_asset_binding_operation() -> None:
    from lib import persian_video_workflow as workflow

    args = workflow.build_parser().parse_args([
        "edit-stage", "run", "f3", "--json", "/tmp/edit.json",
        "--asset-binding-json", "/tmp/binding.json",
    ])
    assert args.asset_binding_json == "/tmp/binding.json"
