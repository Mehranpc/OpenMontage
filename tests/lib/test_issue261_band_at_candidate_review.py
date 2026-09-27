"""#261: a moment carrier's declared band is judged at candidate review.

The first-date run selected four moment shots whose subjects filled the declared
upper band; region review refused them after the search ceiling was spent. The
candidate review now carries the same 10x10 grid and the region-review rule.
"""
from __future__ import annotations

import pytest

from lib.persian_region_commands import PersianRegionCommandError, candidate_band_occupancy


def _grid(**frame):
    return {position: dict(frame) for position in ("start", "middle", "end")}


def test_a_subject_in_the_upper_band_occupies_it():
    # The recorded ve-5 phone: body 29.5%-70% of frame height.
    result = candidate_band_occupancy(
        _grid(priority="hard", grid={"x1": 2, "y1": 2, "x2": 8, "y2": 7}), "upper_band"
    )
    assert result["occupied"] is True
    assert {box["position"] for box in result["occupying"]} == {"start", "middle", "end"}
    assert "upper_band" not in result["clearRegions"]


def test_a_subject_below_the_band_leaves_it_clear():
    # The recorded ve-1 hand and phone sit below row 4.
    result = candidate_band_occupancy(
        _grid(priority="hard", grid={"x1": 0, "y1": 4, "x2": 10, "y2": 9}), "upper_band"
    )
    assert result["occupied"] is False


def test_soft_regions_never_count_like_region_review():
    result = candidate_band_occupancy(
        _grid(priority="soft", grid={"x1": 0, "y1": 0, "x2": 10, "y2": 10}), "upper_band"
    )
    assert result["occupied"] is False


def test_clear_frames_are_clear():
    assert candidate_band_occupancy(_grid(clear=True), "upper_band")["occupied"] is False


def test_all_three_frames_are_required():
    grid = _grid(clear=True)
    del grid["end"]
    with pytest.raises(PersianRegionCommandError, match="end is required"):
        candidate_band_occupancy(grid, "upper_band")


def test_it_agrees_with_region_review_on_the_same_geometry():
    """The region-review rule and the candidate rule are the same rule."""
    from lib.persian_region_commands import declared_negative_space_collisions

    grid = {"x1": 2, "y1": 2, "x2": 8, "y2": 7}
    plan = {"beats": [{"visual_events": [
        {"id": "ve-5", "carries_moment": True, "negative_space": "upper_band"}
    ]}]}
    row = {"shot_id": "shot-5", "avoidRegions": [
        {"x": 0.2, "y": 0.2, "w": 0.6, "h": 0.5, "priority": "hard",
         "startSeconds": 0.0, "endSeconds": 5.0}
    ]}
    at_review = declared_negative_space_collisions(
        plan, [{"shotId": "shot-5", "visualEventId": "ve-5"}], [row]
    )
    at_candidate = candidate_band_occupancy(_grid(priority="hard", grid=grid), "upper_band")
    assert bool(at_review) is at_candidate["occupied"] is True


# -- through the workflow front door ------------------------------------------------

import json
from pathlib import Path

from tests.lib.test_issue35_asset_candidate_workspace import (
    _discovered, _review, _stage, _write_matching_scene_plan,
)


def _workflow(tmp_path: Path, monkeypatch, *, carries_moment: bool):
    from lib import persian_asset_workspace as workspace
    from lib import persian_video_workflow as workflow

    project = tmp_path / "run"
    _write_matching_scene_plan(
        project, **({"carries_moment": True, "negative_space": "upper_band"} if carries_moment else {})
    )
    record = workspace.record_discovery_pass(project, 0, [_discovered(project)])
    candidate = _stage(project, record["candidateIds"][0])
    state = {
        "project_id": "run", "status": "active", "next_phase": "acquire_assets",
        "read_allowlist": {"project_root": str(project)},
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *a, **k: state)
    monkeypatch.setattr(workflow, "assert_read_allowed", lambda _state, path: Path(path))
    return workflow, project, candidate["candidateId"]


def _write_review(project: Path, review: dict) -> str:
    path = project / "review.json"
    path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_a_moment_carrier_review_without_a_grid_is_refused(tmp_path, monkeypatch):
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=True)
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"\[BAND_EVIDENCE_REQUIRED\]"):
        workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, _review()))


def test_footage_filling_the_declared_band_is_refused_before_selection(tmp_path, monkeypatch):
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=True)
    review = _review()
    review["frame_review"]["subject_grid"] = _grid(priority="hard", grid={"x1": 2, "y1": 2, "x2": 8, "y2": 7})
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"\[BAND_OCCUPIED:upper_band\]"):
        workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))


def test_footage_with_a_clear_band_is_recorded(tmp_path, monkeypatch):
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=True)
    review = _review()
    review["frame_review"]["subject_grid"] = _grid(priority="hard", grid={"x1": 0, "y1": 4, "x2": 10, "y2": 9})
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))
    assert result["reviewSha256"]


def test_events_without_a_moment_need_no_grid(tmp_path, monkeypatch):
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=False)
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, _review()))
    assert result["reviewSha256"]
