"""#239: the single asset retry pass is spent only after review, on every rejected event.

On the 58048e2 acceptance run the retry was spent on a pre-review duplicate-source signal.
Review then rejected four events and no in-phase path could re-source them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_video_workflow import (
    PersianVideoWorkflowError,
    bounded_asset_search_request,
    record_asset_search_result,
)
from tests.lib.test_issue35_asset_candidate_workspace import _review
from tests.lib.test_persian_video_workflow import BASE, _asset_result, _bootstrap_to_assets


def _clip(tmp_path: Path, slot: str) -> dict:
    path = tmp_path / "run" / "assets" / "clips" / f"{slot}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 100)
    return {"path": str(path), "file_size_bytes": 100, "source": "pexels", "source_id": slot,
            "clip_id": f"pexels-{slot}", "slot_id": slot, "kind": "video", "duration": 12.0,
            "width": 1080, "height": 1920, "query": f"{slot} query", "license": "Stock License"}


def _first_pass(tmp_path: Path, slots: list[str]) -> Path:
    _bootstrap_to_assets(tmp_path)
    request = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    record_asset_search_result(
        "run", retry_pass=0,
        result_data=_asset_result(request, candidates=len(slots), downloaded_bytes=100 * len(slots),
                                  clips=[_clip(tmp_path, slot) for slot in slots]),
        pipeline_dir=tmp_path, now=BASE,
    )
    return tmp_path / "run"


def _stage(project: Path, slot: str) -> str:
    return workspace.stage_asset_candidate(
        project, discovery_id=workspace._discovery_id("pexels", slot),
        visual_event_id=slot, semantic_beat_id="beat-1", source_in_seconds=0.0, duration_seconds=4.0,
        intended_crop={"mode": "cover", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=1, query=f"{slot} query", narration_span="متن",
    )["candidateId"]


def _retry(tmp_path: Path, slots: list[str]) -> dict:
    return bounded_asset_search_request(
        "run", {"queries": [{"query": f"{slot} alt", "slot_id": slot, "kind": "video"} for slot in slots]},
        retry_pass=1, pipeline_dir=tmp_path, now=BASE,
    )


def test_a_retry_before_any_review_is_refused(tmp_path: Path) -> None:
    _first_pass(tmp_path, ["ev-05", "ev-09"])
    with pytest.raises(PersianVideoWorkflowError, match="before review"):
        _retry(tmp_path, ["ev-05"])


def test_a_retry_with_staged_but_unreviewed_candidates_is_refused(tmp_path: Path) -> None:
    project = _first_pass(tmp_path, ["ev-05"])
    _stage(project, "ev-05")
    with pytest.raises(PersianVideoWorkflowError, match="review or reject staged candidates"):
        _retry(tmp_path, ["ev-05"])


def test_a_retry_must_carry_every_review_rejected_event(tmp_path: Path) -> None:
    project = _first_pass(tmp_path, ["ev-05", "ev-11"])
    for slot in ("ev-05", "ev-11"):
        workspace.reject_asset_candidate(project, _stage(project, slot), category="semantic",
                                         reason="no phone in frame")
    with pytest.raises(PersianVideoWorkflowError, match=r"missing \['ev-11'\]"):
        _retry(tmp_path, ["ev-05"])
    assert _retry(tmp_path, ["ev-05", "ev-11"])["queries"]


def test_reviewed_events_and_events_with_no_footage_are_free_retry_targets(tmp_path: Path) -> None:
    project = _first_pass(tmp_path, ["ev-01"])
    candidate = _stage(project, "ev-01")
    workspace.record_candidate_review(project, candidate, _review())
    assert _retry(tmp_path, ["ev-07"])["queries"]
