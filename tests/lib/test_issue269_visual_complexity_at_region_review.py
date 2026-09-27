"""#269: the opening-hook shot's visualComplexity is a region-review fact.

Film Type 2.16 compose refused a missing value only inside the browser pass, after
a convergence candidate was spent (the first-date rehearsal hit it at edit-stage).
Region review now requires it for every shot under the opening hook, and the cheap
edit precheck names it before any candidate is consumed.
"""
from __future__ import annotations

import copy

import pytest

from lib import persian_region_commands as commands
from lib.persian_edit_contract import collect_persian_edit_diagnostics
from tests.lib.test_persian_region_commands import _annotations, _fake_ffmpeg, _project




def test_opening_shot_without_visual_complexity_is_refused_at_region_review(tmp_path, monkeypatch):
    _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    annotations = _annotations()
    del annotations["shots"][0]["visual_complexity"]

    with pytest.raises(commands.PersianRegionCommandError, match="opening hook: state visual_complexity"):
        commands.propose_regions(tmp_path, "run", annotations)


def test_visual_complexity_is_carried_into_the_proposed_evidence(tmp_path, monkeypatch):
    _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    annotations = _annotations()
    annotations["shots"][0]["visual_complexity"] = "busy"

    result = commands.propose_regions(tmp_path, "run", annotations)

    import json
    from pathlib import Path

    proposal = json.loads(Path(result["proposalPath"]).read_text(encoding="utf-8"))
    rows = {row["shot_id"]: row for row in proposal["proposedEvidence"]["shot_regions"]}
    assert rows["shot-1"]["visualComplexity"] == "busy"
    assert "visualComplexity" not in rows["shot-2"]


def test_an_invalid_visual_complexity_is_refused(tmp_path, monkeypatch):
    _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    annotations = _annotations()
    annotations["shots"][0]["visual_complexity"] = "noisy"

    with pytest.raises(commands.PersianRegionCommandError, match="'simple' or 'busy'"):
        commands.propose_regions(tmp_path, "run", annotations)


def _edit(complexity=None, profile_version=None):
    shot = {"id": "shot-1", "startSeconds": 0.0, "endSeconds": 5.2}
    if complexity:
        shot["visualComplexity"] = complexity
    design = {"version": 2, "profile": "film-type"}
    if profile_version:
        design["profileVersion"] = profile_version
    return {
        "persian": {
            "design": design,
            "shots": [shot, {"id": "shot-2", "startSeconds": 5.2, "endSeconds": 9.0}],
            "moments": [{"id": "m-hook", "kind": "hook", "startSeconds": 0.0, "endSeconds": 5.0}],
        }
    }


def _codes(edit):
    return [item.code for item in collect_persian_edit_diagnostics(edit)]


def test_precheck_names_a_missing_hook_shot_complexity_without_a_browser():
    assert "shot.visual_complexity_missing" in _codes(_edit())


def test_precheck_accepts_a_reviewed_value_and_ignores_later_shots():
    assert "shot.visual_complexity_missing" not in _codes(_edit("simple"))


def test_precheck_leaves_older_pinned_profiles_alone():
    assert "shot.visual_complexity_missing" not in _codes(_edit(profile_version="2.15.0"))
