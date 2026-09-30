"""#341: candidate copy is measured before selection, not after retry expenditure."""
from __future__ import annotations

import json

import pytest

from lib import persian_asset_workspace as workspace
from lib import persian_region_commands as regions
from lib.persian_film_type import FilmTypePreflightError
from tests.lib.test_issue261_band_at_candidate_review import _grid, _workflow, _write_review
from tests.lib.test_issue35_asset_candidate_workspace import _review
from tests.lib.test_issue312_carrier_moment_placement import browser


def _setup(tmp_path, monkeypatch):
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=True)
    path = project / "checkpoint_scene_plan.json"
    checkpoint = json.loads(path.read_text())
    plan = checkpoint["artifacts"]["scene_plan"]
    event = plan["beats"][0]["visual_events"][0]
    event["moment_copy"] = [{"role": "hero", "text": "۵۴۳ نفر"},
                            {"role": "tail", "text": "یک قرار اول را تصور کردند"}]
    path.write_text(json.dumps(checkpoint))
    review = _review()
    review["frame_review"]["subject_grid"] = _grid(
        priority="hard", grid={"x1": 0, "y1": 4, "x2": 10, "y2": 9})
    return workflow, project, candidate, review


def test_review_measures_actual_copy_window_and_grid_before_recording(tmp_path, monkeypatch, browser):
    calls, _ = browser
    workflow, project, candidate, review = _setup(tmp_path, monkeypatch)
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))
    assert result["carrierPremeasure"]["results"][0]["feasible"] is True
    props = calls[0]
    assert props["moments"][0]["segments"][0]["text"] == "۵۴۳ نفر"
    assert props["durationSeconds"] == 4.0
    assert len(props["shots"][0]["avoidRegions"]) == 3
    assert props["shots"][0]["avoidRegions"][0]["y"] == 0.4
    assert workspace.load_asset_candidate(project, candidate)["disposition"] == "reviewed"


def test_measured_collision_leaves_candidate_unreviewed(tmp_path, monkeypatch, browser):
    _, outcome = browser
    outcome["raise"] = FilmTypePreflightError(
        "no safe measured placement remains", code="ASSET_SELECTION_HARD_REGION_COLLISION")
    workflow, project, candidate, review = _setup(tmp_path, monkeypatch)
    before = workspace.load_asset_candidate(project, candidate)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="CARRIER_COPY_UNPLACEABLE"):
        workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))
    assert workspace.load_asset_candidate(project, candidate) == before


def test_other_layout_error_is_unknown_not_fit_approval(tmp_path, monkeypatch, browser):
    _, outcome = browser
    outcome["raise"] = FilmTypePreflightError("unsupported recipe", code="FILM_TYPE_PREPASS")
    workflow, project, candidate, review = _setup(tmp_path, monkeypatch)
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))
    assert result["carrierPremeasure"]["status"] == "unknown"
    assert result["carrierPremeasure"]["results"][0]["feasible"] is None


def test_missing_font_reports_unknown(tmp_path, monkeypatch):
    import tools.video.persian_compose as compose

    monkeypatch.setattr(compose, "_composer_dir", lambda: tmp_path / "no-composer")
    workflow, project, candidate, review = _setup(tmp_path, monkeypatch)
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))
    assert result["carrierPremeasure"]["status"] == "unknown"


def test_non_carriers_do_not_start_a_browser(tmp_path, monkeypatch, browser):
    calls, _ = browser
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=False)
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, _review()))
    assert result["carrierPremeasure"]["status"] == "not_applicable"
    assert calls == []


def test_missing_copy_is_unknown_and_does_not_start_a_browser(tmp_path, monkeypatch, browser):
    calls, _ = browser
    workflow, project, candidate = _workflow(tmp_path, monkeypatch, carries_moment=True)
    review = _review()
    review["frame_review"]["subject_grid"] = _grid(clear=True)
    result = workflow.review_workflow_asset_candidate("run", candidate, _write_review(project, review))
    assert result["carrierPremeasure"] == {
        "status": "unknown", "reason": "moment_copy_unavailable", "results": [],
    }
    assert calls == []


def test_candidate_probe_respects_plan_format_and_soft_regions(browser):
    calls, _ = browser
    result = regions.candidate_carrier_placement(
        {"format": "landscape", "beats": [{"visual_events": [{"id": "event", "carries_moment": True,
          "moment_copy": [{"role": "hero", "text": "نمونه"}]}]}]},
        {"candidateId": "candidate", "context": {"visualEventId": "event"},
         "identity": {"sourceWindow": {"startSeconds": 10.0, "endSeconds": 15.0}}},
        _grid(priority="soft", grid={"x1": 0, "y1": 0, "x2": 10, "y2": 10}),
    )
    assert result["status"] == "checked"
    assert calls[0]["format"] == "landscape"
    assert calls[0]["durationSeconds"] == 5.0
    assert all(r["priority"] == "soft" for r in calls[0]["shots"][0]["avoidRegions"])
