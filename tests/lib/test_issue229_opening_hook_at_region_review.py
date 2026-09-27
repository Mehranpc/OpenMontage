"""#229: an opening shot that leaves no Film Type hook zone clear is found at region review."""

from __future__ import annotations

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_region_commands import _HOOK_ZONES, _hook_zone_rect, opening_hook_placement


def _shots(*spans):
    return [{"shotId": f"shot-{i + 1}", "timeline": {"startSeconds": a, "endSeconds": b}}
            for i, (a, b) in enumerate(spans)]


def _rows(**regions):
    return [{"shot_id": shot, "avoidRegions": rs} for shot, rs in regions.items()]


def test_a_centre_subject_that_covers_every_zone_is_infeasible() -> None:
    whole = {"x": 0.08, "y": 0.14, "w": 0.84, "h": 0.51, "priority": "hard",
             "startSeconds": 0.0, "endSeconds": 5.0}
    finding = opening_hook_placement(_shots((0.0, 5.8), (5.8, 10.0)), _rows(**{"shot-1": [whole]}))
    assert finding["feasible"] is False
    assert finding["shotIds"] == ["shot-1"]
    assert set(finding["blockedZones"]) == set(_HOOK_ZONES)


def test_the_rerender_face_leaves_mid_right_clear() -> None:
    """The re-render's opening: face upper-middle, marked hard; the hook fit at mid-right."""
    face = {"x": 0.3, "y": 0.1, "w": 0.45, "h": 0.25, "priority": "hard",
            "startSeconds": 0.0, "endSeconds": 5.6}
    finding = opening_hook_placement(_shots((0.0, 5.8)), _rows(**{"shot-1": [face]}))
    assert finding["feasible"] is True
    assert "mid-right" in finding["clearZones"]
    assert "upper-right" in finding["blockedZones"]


def test_soft_regions_and_later_shots_do_not_block() -> None:
    soft = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "priority": "soft"}
    late = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "priority": "hard"}
    finding = opening_hook_placement(
        _shots((0.0, 6.0), (6.0, 12.0)), _rows(**{"shot-1": [soft], "shot-2": [late]})
    )
    assert finding["feasible"] is True and finding["shotIds"] == ["shot-1"]


def test_zone_rects_stay_inside_the_vertical_safe_area() -> None:
    for zone in _HOOK_ZONES:
        x, y, w, h = _hook_zone_rect(zone)
        assert x >= 0.08 - 1e-9 and x + w <= 0.92 + 1e-9
        assert y >= 0.14 - 1e-9 and y + h <= 0.65 + 1e-6


def test_completion_names_the_unplaceable_opening(monkeypatch, tmp_path) -> None:
    from lib import persian_region_commands as commands

    monkeypatch.setattr(workflow, "_project_root", lambda _state: tmp_path)
    monkeypatch.setattr(commands, "pending_negative_space_collisions", lambda _p: [])
    monkeypatch.setattr(commands, "pending_opening_hook_block", lambda _p: {
        "shotIds": ["shot-1"], "feasible": False, "clearZones": [],
        "blockedZones": {"upper-right": ["shot-1#0"]},
    })
    with pytest.raises(workflow.PersianVideoWorkflowError, match="OPENING_HOOK_UNPLACEABLE"):
        workflow._refuse_declared_negative_space_collisions({})
