"""#248: region review and the edit stage agree on what occupies a declared region.

Region review ignores `priority: soft` (body occupancy), but the edit rule counted it.
On the fd2fb05 rerun, shot-6 was certified clear at region review and then refused at
edit, which cost a plan re-declaration and a re-acquisition past the wall budget.
"""

from __future__ import annotations

from lib.persian_edit_workspace import _declared_region_is_clear
from lib.persian_region_commands import declared_negative_space_collisions
from lib.persian_scenes import _NEGATIVE_SPACE_RECTS

PLAN = {"beats": [{"id": "beat-6", "visual_events": [
    {"id": "ve-06", "carries_moment": True, "negative_space": "centre_band"}]}]}


def _region(priority: str) -> dict:
    x, y, w, h = _NEGATIVE_SPACE_RECTS["centre_band"]
    return {"x": x + w / 4, "y": y, "w": w / 2, "h": h, "priority": priority}


def _both(priority: str) -> tuple[list, list]:
    region = _region(priority)
    review = declared_negative_space_collisions(
        PLAN, [{"shotId": "shot-6", "visualEventId": "ve-06"}],
        [{"shot_id": "shot-6", "avoidRegions": [region]}],
    )
    edit = _declared_region_is_clear(
        {"persian": {"shots": [{"id": "shot-6", "visualEventId": "ve-06", "avoidRegions": [region]}]}},
        PLAN,
    )
    return review, edit


def test_soft_body_occupancy_is_clear_at_both_gates() -> None:
    review, edit = _both("soft")
    assert review == [] and edit == []


def test_hard_occupancy_is_refused_at_both_gates() -> None:
    review, edit = _both("hard")
    assert review and edit
