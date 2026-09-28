"""#312: region review asks the Film Type prepass whether each carrier's moment fits.

The real browser decision is pinned in tests/l2/test_issue312_moment_placement_probe.py
(the f418063 moment-3 on shot-4's regions). These tests pin the wiring: which props the
probe builds, which outcomes block, and that an unavailable browser never blocks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_region_commands as regions
from lib.persian_film_type import FilmTypePreflightError

PLAN = {"beats": [{"id": "b4", "visual_events": [
    {"id": "ev-4", "carries_moment": True,
     "moment_copy": [{"role": "hero", "text": "۵۴۳ نفر"}, {"role": "tail", "text": "یک قرار اول را تصور کردند"}]},
    {"id": "ev-5", "carries_moment": False},
]}]}
SHOTS = [
    {"shotId": "shot-4", "visualEventId": "ev-4", "timeline": {"startSeconds": 13.34, "endSeconds": 19.37}},
    {"shotId": "shot-5", "visualEventId": "ev-5", "timeline": {"startSeconds": 19.37, "endSeconds": 22.0}},
]
ROWS = [{"shot_id": "shot-4", "avoidRegions": [
    {"x": 0.0, "y": 0.42, "w": 1.0, "h": 0.58, "priority": "soft", "startSeconds": 13.34, "endSeconds": 19.37},
    {"x": 0.5, "y": 0.42, "w": 0.2, "h": 0.18, "priority": "hard", "startSeconds": 13.34, "endSeconds": 19.37},
]}]


@pytest.fixture()
def browser(tmp_path, monkeypatch):
    composer = tmp_path / "composer"
    (composer / "public" / "fonts" / "kahroba").mkdir(parents=True)
    (composer / "public" / "fonts" / "kahroba" / "Kahroba-EB-LC.woff2").write_bytes(b"x")
    import tools.video.persian_compose as compose

    monkeypatch.setattr(compose, "_composer_dir", lambda: composer)
    monkeypatch.setattr(regions.shutil, "which", lambda name: "/usr/bin/node")
    calls: list[dict] = []
    outcome: dict = {"raise": None}

    def fake_prepare(props, _composer, **_):
        calls.append(props)
        if outcome["raise"]:
            raise outcome["raise"]
        return props

    import lib.persian_film_type as film_type

    monkeypatch.setattr(film_type, "prepare_film_type_props", fake_prepare)
    return calls, outcome


def test_only_carriers_are_probed_with_their_copy_and_reviewed_regions(browser) -> None:
    calls, _ = browser
    result = regions.carrier_moment_placement(PLAN, SHOTS, ROWS)
    assert result == {"status": "checked", "results": [
        {"shotId": "shot-4", "visualEventId": "ev-4", "feasible": True}]}
    props = calls[0]
    moment = props["moments"][0]
    assert moment["kind"] == "figure"  # hero starts with a numeral
    assert [s["text"] for s in moment["segments"]] == ["۵۴۳ نفر", "یک قرار اول را تصور کردند"]
    shot = props["shots"][0]
    assert shot["endSeconds"] == pytest.approx(6.03)
    assert [r["priority"] for r in shot["avoidRegions"]] == ["soft", "hard"]
    assert shot["avoidRegions"][1]["startSeconds"] == 0.0


def test_a_hard_region_refusal_is_a_finding(browser) -> None:
    _, outcome = browser
    outcome["raise"] = FilmTypePreflightError(
        "Film Type ...\nMoment probe-ev-4: no safe measured placement remains",
        code="ASSET_SELECTION_HARD_REGION_COLLISION")
    result = regions.carrier_moment_placement(PLAN, SHOTS, ROWS)
    assert result["status"] == "refused"
    assert result["results"][0]["feasible"] is False
    assert "no safe measured placement" in result["results"][0]["message"]


def test_any_other_refusal_is_unknown_not_blocking(browser) -> None:
    _, outcome = browser
    outcome["raise"] = FilmTypePreflightError("recipe occupancy", code="FILM_TYPE_PREPASS")
    result = regions.carrier_moment_placement(PLAN, SHOTS, ROWS)
    assert result["status"] == "checked"
    assert result["results"][0]["feasible"] is None


def test_no_font_means_no_probe(tmp_path, monkeypatch) -> None:
    import tools.video.persian_compose as compose

    monkeypatch.setattr(compose, "_composer_dir", lambda: tmp_path)
    assert regions.carrier_moment_placement(PLAN, SHOTS, ROWS)["status"] == "unknown"


def test_the_completion_gate_names_the_unplaceable_carrier(tmp_path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    monkeypatch.setattr(regions, "pending_opening_hook_block", lambda project: None)
    monkeypatch.setattr(regions, "pending_negative_space_collisions", lambda project: [])
    monkeypatch.setattr(regions, "pending_unplaceable_moments", lambda project: [
        {"shotId": "shot-4", "visualEventId": "ev-4", "feasible": False}])
    monkeypatch.setattr(workflow, "_project_root", lambda state: tmp_path)
    fn = workflow._refuse_declared_negative_space_collisions
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"\[MOMENT_UNPLACEABLE\].*shot-4 \(ev-4\)"):
        fn({"project_root": str(tmp_path)})
