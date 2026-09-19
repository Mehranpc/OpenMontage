from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_asset_workspace import PersianAssetWorkspaceError


def _discovered(project: Path, *, provider: str = "pexels", source_id: str = "source-1", name: str = "clip.mp4", duration: float = 12.0, slot_id: str = "event-1") -> dict:
    path = project / "assets" / "clips" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return {
        "clip_id": f"{provider}-{source_id}",
        "source": provider,
        "source_id": source_id,
        "source_url": f"https://example.test/{provider}/{source_id}",
        "query": "person thinking at desk",
        "slot_id": slot_id,
        "kind": "video",
        "path": str(path),
        "duration": duration,
        "width": 1080,
        "height": 1920,
        "creator": "Creator",
        "license": "Stock License",
        "source_tags": ["person", "desk"],
    }


def _stage(project: Path, discovery_id: str, *, event: str = "event-1", start: float = 0.0, duration: float = 4.0, crop: dict | None = None, rank: int = 1) -> dict:
    return workspace.stage_asset_candidate(
        project,
        discovery_id=discovery_id,
        visual_event_id=event,
        semantic_beat_id="beat-1",
        source_in_seconds=start,
        duration_seconds=duration,
        intended_crop=crop or {"mode": "cover", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=rank,
        query="person thinking at desk",
        narration_span="این یک جمله نمونه است",
    )


def _review(*, relevance: str = "The visible action matches the beat.", resolution_quality: str = "strong") -> dict:
    return {
        "frame_review": {"start": True, "middle": True, "end": True, "observed": "Subject stays visible across the selected crop."},
        "shows_subject": True,
        "human_presence": True,
        "affect_match": True,
        "staged_stock_risk": "low",
        "relevance_reason": relevance,
        "selection_reason": "A real person remains visible and readable in the crop.",
        "geometry_review": {"crop_safe": True, "negative_space": "right", "observed": "Usable right-side negative space."},
        "resolution_quality": resolution_quality,
    }


def test_candidate_identity_binds_provider_source_window_and_crop(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery = workspace.record_discovery_pass(project, 0, [_discovered(project)])
    discovery_id = discovery["candidateIds"][0]

    first = _stage(project, discovery_id, start=1.0, duration=4.0)
    same = _stage(project, discovery_id, start=1.0, duration=4.0)
    shifted = _stage(project, discovery_id, start=5.0, duration=4.0)
    cropped = _stage(project, discovery_id, start=1.0, duration=4.0, crop={"mode": "cover", "x": 0.1, "y": 0.0, "w": 0.8, "h": 1.0})

    assert same["candidateId"] == first["candidateId"]
    assert same["idempotent"] is True
    assert shifted["candidateId"] != first["candidateId"]
    assert cropped["candidateId"] != first["candidateId"]
    manifest = workspace.load_asset_candidate(project, first["candidateId"])
    assert manifest["identity"]["provider"] == "pexels"
    assert manifest["identity"]["sourceId"] == "source-1"
    assert manifest["identity"]["sourceWindow"] == {"startSeconds": 1.0, "endSeconds": 5.0}


def test_review_evidence_is_bound_once_to_candidate_identity_and_reused(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_id = workspace.record_discovery_pass(project, 0, [_discovered(project)])["candidateIds"][0]
    candidate = _stage(project, discovery_id)
    first = workspace.record_candidate_review(project, candidate["candidateId"], _review())
    again = workspace.record_candidate_review(project, candidate["candidateId"], _review())
    assert first["reviewSha256"] == again["reviewSha256"]
    assert again["idempotent"] is True
    assert workspace.reusable_asset_candidates(project, visual_event_id="event-1")[0]["candidateId"] == candidate["candidateId"]
    with pytest.raises(PersianAssetWorkspaceError, match="review evidence is immutable"):
        workspace.record_candidate_review(project, candidate["candidateId"], _review(relevance="Changed after review"))


def test_overlapping_same_source_windows_are_rejected_but_nonoverlap_is_legal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_id = workspace.record_discovery_pass(project, 0, [_discovered(project, duration=14.0)])["candidateIds"][0]
    first = _stage(project, discovery_id, event="event-1", start=0.0, duration=4.0)
    overlap = _stage(project, discovery_id, event="event-2", start=3.0, duration=4.0)
    distinct = _stage(project, discovery_id, event="event-3", start=5.0, duration=4.0)
    for item in (first, overlap, distinct):
        workspace.record_candidate_review(project, item["candidateId"], _review())

    workspace.select_asset_candidate(project, "event-1", first["candidateId"], rejected_alternatives={})
    with pytest.raises(PersianAssetWorkspaceError, match="visible source-window overlap"):
        workspace.select_asset_candidate(project, "event-2", overlap["candidateId"], rejected_alternatives={})
    selected = workspace.select_asset_candidate(project, "event-3", distinct["candidateId"], rejected_alternatives={})
    assert selected["selected"] is True


def test_rejection_taxonomy_distinguishes_technical_semantic_and_editorial(tmp_path: Path) -> None:
    project = tmp_path / "project"
    ids = workspace.record_discovery_pass(
        project, 0,
        [
            _discovered(project, source_id="technical", name="technical.mp4"),
            _discovered(project, source_id="semantic", name="semantic.mp4"),
            _discovered(project, source_id="editorial", name="editorial.mp4"),
        ],
    )["candidateIds"]
    categories = ["technical", "semantic", "editorial"]
    for discovery_id, category in zip(ids, categories):
        candidate = _stage(project, discovery_id, event=f"event-{category}")
        rejected = workspace.reject_asset_candidate(project, candidate["candidateId"], category=category, reason=f"{category} reason")
        assert rejected["rejection"]["category"] == category
    status = workspace.asset_workspace_status(project)
    assert status["rejectionCounts"] == {"technical": 1, "semantic": 1, "editorial": 1}


def test_selected_candidate_records_reasons_for_reviewed_alternates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_ids = workspace.record_discovery_pass(
        project, 0,
        [
            _discovered(project, source_id="a", name="a.mp4"),
            _discovered(project, source_id="b", name="b.mp4"),
        ],
    )["candidateIds"]
    first = _stage(project, discovery_ids[0], rank=1)
    alternate = _stage(project, discovery_ids[1], rank=2)
    for item in (first, alternate):
        workspace.record_candidate_review(project, item["candidateId"], _review())

    with pytest.raises(PersianAssetWorkspaceError, match="reviewed alternatives require rejection reasons"):
        workspace.select_asset_candidate(project, "event-1", first["candidateId"], rejected_alternatives={})
    result = workspace.select_asset_candidate(
        project,
        "event-1",
        first["candidateId"],
        rejected_alternatives={alternate["candidateId"]: "Less semantic specificity."},
    )
    assert result["selection"]["rejectedAlternatives"][alternate["candidateId"]] == "Less semantic specificity."


def test_reviewed_alternate_can_be_reused_without_rediscovery_or_rereview(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_ids = workspace.record_discovery_pass(
        project, 0,
        [
            _discovered(project, source_id="a", name="a.mp4"),
            _discovered(project, source_id="b", name="b.mp4"),
        ],
    )["candidateIds"]
    primary = _stage(project, discovery_ids[0], rank=1)
    alternate = _stage(project, discovery_ids[1], rank=2)
    for item in (primary, alternate):
        workspace.record_candidate_review(project, item["candidateId"], _review())
    workspace.select_asset_candidate(
        project, "event-1", primary["candidateId"],
        rejected_alternatives={alternate["candidateId"]: "Second-best framing."},
    )
    switched = workspace.select_asset_candidate(
        project, "event-1", alternate["candidateId"],
        rejected_alternatives={primary["candidateId"]: "User-directed replacement."},
        replace_existing=True,
    )
    assert switched["selection"]["candidateId"] == alternate["candidateId"]
    assert workspace.asset_workspace_status(project)["discoveryPassCount"] == 1
    assert workspace.load_asset_candidate(project, alternate["candidateId"])["reviewSha256"]


def test_weak_resolution_selection_is_visible_before_asset_completion(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_id = workspace.record_discovery_pass(project, 0, [_discovered(project)])["candidateIds"][0]
    candidate = workspace.stage_asset_candidate(
        project,
        discovery_id=discovery_id,
        visual_event_id="ending-event",
        semantic_beat_id="ending-beat",
        narrative_role="resolution",
        source_in_seconds=0.0,
        duration_seconds=4.0,
        intended_crop={"mode": "cover", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=1,
        query="person thinking at desk",
        narration_span="پایان",
    )
    workspace.record_candidate_review(project, candidate["candidateId"], _review(resolution_quality="weak"))
    workspace.select_asset_candidate(project, "ending-event", candidate["candidateId"], rejected_alternatives={})
    status = workspace.asset_workspace_status(project)
    assert status["weakSelectionWarnings"]
    assert status["weakSelectionWarnings"][0]["visualEventId"] == "ending-event"
    assert status["weakSelectionWarnings"][0]["reason"] == "weak_resolution_quality"


def test_asset_search_result_populates_workspace_discovery_pool(tmp_path: Path) -> None:
    from tests.lib.test_persian_video_workflow import BASE, _asset_result, _bootstrap_to_assets
    from lib.persian_video_workflow import bounded_asset_search_request, record_asset_search_result

    _bootstrap_to_assets(tmp_path)
    request = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    project = tmp_path / "run"
    clip = _discovered(project, source_id="auto-import", name="auto.mp4")
    clip["file_size_bytes"] = Path(clip["path"]).stat().st_size
    result = _asset_result(request, candidates=1, downloaded_bytes=clip["file_size_bytes"], clips=[clip])
    state = record_asset_search_result(
        "run", retry_pass=0, result_data=result, pipeline_dir=tmp_path, now=BASE
    )

    status = workspace.asset_workspace_status(project)
    assert status["discoveryPassCount"] == 1
    assert status["discoveryCandidateCount"] == 1
    assert state["asset_usage"]["workspace_discovery_candidates"] == 1


def test_workflow_status_surfaces_asset_workspace_state(tmp_path: Path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    project = tmp_path / "run"
    state = {
        "project_id": "run",
        "status": "active",
        "next_phase": "acquire_assets",
        "input": {},
        "completed_phases": [],
        "attempts": {},
        "send_backs": 0,
        "recovery_attempts": {},
        "asset_usage": {},
        "alignment_policy": {},
        "read_allowlist": {"project_root": str(project)},
        "user_revision_cycles": 0,
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(workflow, "phase_time_accounting", lambda _state: {})
    monkeypatch.setattr(workflow, "convergence_status", lambda *args, **kwargs: {"status": "active"})
    monkeypatch.setattr(
        workflow,
        "asset_workspace_status",
        lambda project_dir: {
            "discoveryPassCount": 1,
            "candidateCount": 3,
            "reviewedCandidateCount": 2,
            "selectedCount": 1,
            "rejectionCounts": {"technical": 0, "semantic": 1, "editorial": 0},
            "weakSelectionWarnings": [],
        },
    )
    status = workflow.workflow_status("run", pipeline_dir=tmp_path)
    assert status["asset_workspace"]["candidateCount"] == 3
    assert status["asset_workspace"]["selectedCount"] == 1


def test_front_door_exposes_asset_candidate_lifecycle_commands() -> None:
    from lib import persian_video_workflow as workflow

    parser = workflow.build_parser()
    staged = parser.parse_args(["asset-candidate-stage", "run", "--json", "/tmp/candidate.json"])
    assert staged.command == "asset-candidate-stage"
    reviewed = parser.parse_args(["asset-candidate-review", "run", "asset-1", "--json", "/tmp/review.json"])
    assert reviewed.command == "asset-candidate-review"
    rejected = parser.parse_args([
        "asset-candidate-reject", "run", "asset-1", "--category", "semantic", "--reason", "wrong meaning"
    ])
    assert rejected.category == "semantic"
    selected = parser.parse_args([
        "asset-candidate-select", "run", "event-1", "asset-1",
        "--rejections-json", "/tmp/rejections.json", "--replace-existing",
    ])
    assert selected.command == "asset-candidate-select"
    assert selected.replace_existing is True


def _selected_candidate(project: Path, *, event: str = "event-1") -> tuple[dict, dict]:
    discovery_id = workspace.record_discovery_pass(
        project, 0, [_discovered(project, source_id="selected", name="selected.mp4", slot_id=event)]
    )["candidateIds"][0]
    candidate = workspace.stage_asset_candidate(
        project,
        discovery_id=discovery_id,
        visual_event_id=event,
        semantic_beat_id="beat-1",
        narrative_role="resolution" if event == "ending-event" else "exposition",
        source_in_seconds=1.0,
        duration_seconds=4.0,
        intended_crop={"mode": "cover", "x": 0.1, "y": 0.0, "w": 0.8, "h": 1.0},
        candidate_rank=1,
        query="person thinking at desk",
        narration_span="این یک جمله نمونه است",
    )
    workspace.record_candidate_review(project, candidate["candidateId"], _review())
    selected = workspace.select_asset_candidate(
        project, event, candidate["candidateId"], rejected_alternatives={}
    )
    return candidate, selected


def test_selection_returns_canonical_manifest_binding_fields(tmp_path: Path) -> None:
    project = tmp_path / "project"
    candidate, selected = _selected_candidate(project)
    binding = selected["manifestBinding"]
    assert binding == {
        "asset_candidate_id": candidate["candidateId"],
        "asset_candidate_identity_sha256": candidate["identitySha256"],
        "asset_review_sha256": workspace.load_asset_candidate(project, candidate["candidateId"])["reviewSha256"],
        "provider": "pexels",
        "source_id": "selected",
        "source_in_seconds": 1.0,
        "source_window_end_seconds": 5.0,
        "duration_seconds": 12.0,
        "intended_crop": {"mode": "cover", "x": 0.1, "y": 0.0, "w": 0.8, "h": 1.0},
    }


def test_asset_manifest_schema_accepts_workspace_binding_provenance() -> None:
    from schemas.artifacts import validate_artifact

    manifest = {
        "version": "1.0",
        "assets": [{
            "id": "asset-1",
            "type": "video",
            "path": "projects/run/assets/clip.mp4",
            "source_tool": "direct_clip_search",
            "scene_id": "scene-1",
            "visual_event_id": "event-1",
            "provider": "pexels",
            "source_id": "source-1",
            "source_in_seconds": 1.0,
            "source_window_end_seconds": 5.0,
            "duration_seconds": 12.0,
            "intended_crop": {"mode": "cover", "x": 0.1, "y": 0.0, "w": 0.8, "h": 1.0},
            "asset_candidate_id": "asset-abc",
            "asset_candidate_identity_sha256": "a" * 64,
            "asset_review_sha256": "b" * 64,
        }],
    }
    validate_artifact("asset_manifest", manifest)


def test_manifest_binding_rejects_missing_or_changed_selected_identity(tmp_path: Path) -> None:
    project = tmp_path / "project"
    candidate, selected = _selected_candidate(project)
    binding = dict(selected["manifestBinding"])
    evidence = dict(selected["manifestEvidence"])
    base_asset = {
        "id": "asset-1", "type": "video", "path": "unused.mp4",
        "source_tool": "direct_clip_search", "scene_id": "scene-1",
        **binding, **evidence,
    }
    valid = workspace.validate_asset_manifest_against_workspace(
        project, {"version": "1.0", "assets": [base_asset]}
    )
    assert valid["enforced"] is True
    assert valid["selectedCount"] == 1

    missing = dict(base_asset)
    missing.pop("asset_candidate_id")
    with pytest.raises(PersianAssetWorkspaceError, match="asset_candidate_id"):
        workspace.validate_asset_manifest_against_workspace(
            project, {"version": "1.0", "assets": [missing]}
        )

    changed = dict(base_asset)
    changed["source_window_end_seconds"] = 6.0
    with pytest.raises(PersianAssetWorkspaceError, match="source_window_end_seconds"):
        workspace.validate_asset_manifest_against_workspace(
            project, {"version": "1.0", "assets": [changed]}
        )

    # Rejected/discovery history is not canonical selection state and therefore
    # does not require a manifest row.
    extra_discovery = workspace.record_discovery_pass(
        project, 1, [_discovered(project, source_id="unused", name="unused.mp4")]
    )["candidateIds"][0]
    unused = _stage(project, extra_discovery, event="event-unused")
    workspace.reject_asset_candidate(project, unused["candidateId"], category="semantic", reason="Not relevant")
    assert workspace.validate_asset_manifest_against_workspace(
        project, {"version": "1.0", "assets": [base_asset]}
    )["selectedCount"] == 1


def test_manifest_binding_is_backward_compatible_without_workspace_selections(tmp_path: Path) -> None:
    project = tmp_path / "project"
    result = workspace.validate_asset_manifest_against_workspace(
        project, {"version": "1.0", "assets": []}
    )
    assert result == {"enforced": False, "selectedCount": 0, "validatedVisualEventIds": []}


def test_acquire_assets_completion_consumes_workspace_manifest_binding(tmp_path: Path, monkeypatch) -> None:
    from tests.lib.test_persian_video_workflow import BASE, _bootstrap_to_assets
    from lib import persian_video_workflow as workflow

    _bootstrap_to_assets(tmp_path)
    workflow.record_phase_attempt("run", "acquire_assets", pipeline_dir=tmp_path, now=BASE)
    checkpoint = {
        "status": "completed",
        "artifacts": {"asset_manifest": {"version": "1.0", "assets": []}},
    }
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args, **kwargs: checkpoint)
    observed = {}

    def fake_validate(project_dir, manifest):
        observed["project_dir"] = project_dir
        observed["manifest"] = manifest
        return {"enforced": True, "selectedCount": 2, "validatedVisualEventIds": ["e1", "e2"]}

    monkeypatch.setattr(workflow, "validate_asset_manifest_against_workspace", fake_validate)
    state = workflow.complete_phase(
        "run", "acquire_assets", pipeline_dir=tmp_path, now=BASE
    )
    assert observed["manifest"] == checkpoint["artifacts"]["asset_manifest"]
    assert state["evidence"]["acquire_assets"]["assetWorkspaceBinding"]["selectedCount"] == 2


def test_selection_returns_manifest_semantic_evidence_and_rejects_drift(tmp_path: Path) -> None:
    project = tmp_path / "project"
    candidate, selected = _selected_candidate(project)
    evidence = selected["manifestEvidence"]
    assert evidence["visual_event_id"] == "event-1"
    assert evidence["semantic_beat_id"] == "beat-1"
    assert evidence["query"] == "person thinking at desk"
    assert evidence["candidate_rank"] == 1
    assert evidence["narration_span"] == "این یک جمله نمونه است"
    assert evidence["relevance_reason"] == "The visible action matches the beat."
    assert evidence["selection_reason"] == "A real person remains visible and readable in the crop."
    assert evidence["affect_match"] is True
    assert evidence["staged_stock_risk"] == "low"
    assert evidence["human_presence"] is True
    assert evidence["shows_subject"] is True
    assert evidence["frame_review"]["observed"]

    asset = {
        "id": "asset-1", "type": "video", "path": "unused.mp4",
        "source_tool": "direct_clip_search", "scene_id": "scene-1",
        **selected["manifestBinding"], **evidence,
    }
    assert workspace.validate_asset_manifest_against_workspace(
        project, {"version": "1.0", "assets": [asset]}
    )["enforced"] is True

    drifted = dict(asset)
    drifted["relevance_reason"] = "A different explanation reconstructed later."
    with pytest.raises(PersianAssetWorkspaceError, match="relevance_reason"):
        workspace.validate_asset_manifest_against_workspace(
            project, {"version": "1.0", "assets": [drifted]}
        )
