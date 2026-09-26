"""#214: a declared-region collision is found at region review, not after edit candidates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_region_commands as commands
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_region_commands import _annotations, _fake_ffmpeg, _project


def _declare(project: Path, **regions: str) -> None:
    """Mark events carries_moment with a declared negative_space."""
    path = project / "artifacts" / "scene_plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    for beat in plan["beats"]:
        for event in beat.get("visual_events") or []:
            if event["id"] in regions:
                event["carries_moment"] = True
                event["negative_space"] = regions[event["id"]]
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def test_every_collision_is_reported_in_one_pass(tmp_path: Path, monkeypatch) -> None:
    # shot-1 hard region spans rows 2-8 (y 0.2-0.8): upper_band (y<0.33) collides.
    # shot-2 hard region is x 0-0.5, y 0.1-0.9: upper_band collides, right_column is clear.
    project = _project(tmp_path)
    _declare(project, **{"event-1": "upper_band", "event-2": "upper_band"})
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")

    result = commands.propose_regions(tmp_path, "run", _annotations())

    assert result["negativeSpaceClear"] is False
    rows = {row["shotId"]: row for row in result["negativeSpaceCollisions"]}
    assert set(rows) == {"shot-1", "shot-2"}
    assert rows["shot-1"]["declaredRegion"] == "upper_band"
    assert "right_column" in rows["shot-2"]["regionsClearOfTheseHardRegions"]
    proposal = json.loads(Path(result["proposalPath"]).read_text(encoding="utf-8"))
    assert proposal["negativeSpaceCollisions"] == result["negativeSpaceCollisions"]


def test_soft_regions_and_clear_declarations_do_not_collide(tmp_path: Path, monkeypatch) -> None:
    # shot-2's soft region occupies the right column; soft never counts, as in the edit rule.
    project = _project(tmp_path)
    _declare(project, **{"event-2": "right_column"})
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")

    result = commands.propose_regions(tmp_path, "run", _annotations())

    assert result["negativeSpaceCollisions"] == []
    assert result["negativeSpaceClear"] is True


def test_region_review_cannot_complete_over_a_pending_collision(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    _declare(project, **{"event-1": "upper_band"})
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    commands.propose_regions(tmp_path, "run", _annotations())

    state = {"project_root": str(project), "projects_root": str(tmp_path), "project_id": "run"}
    monkeypatch.setattr(workflow, "_project_root", lambda _state: project)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="DECLARED_NEGATIVE_SPACE_OCCUPIED") as excinfo:
        workflow._refuse_declared_negative_space_collisions(state)
    assert "shot-1 (event-1)" in str(excinfo.value)


def test_a_proposal_for_an_older_plan_is_not_a_finding(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    _declare(project, **{"event-1": "upper_band"})
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    commands.propose_regions(tmp_path, "run", _annotations())
    assert commands.pending_negative_space_collisions(project)

    _declare(project, **{"event-1": "lower_band"})  # the plan was fixed after the proposal
    assert commands.pending_negative_space_collisions(project) == []


def test_no_proposal_means_no_refusal(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr(workflow, "_project_root", lambda _state: project)
    workflow._refuse_declared_negative_space_collisions({})
