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
