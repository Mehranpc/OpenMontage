"""#335 (c): a moment carrier may accept several bands, and is refused only when all are occupied.

The 2026-09-29 run needed 5 of 8 carriers to leave the upper band clear and got a
phone across it for most of them, although the centre band was often free. A carrier
now declares `negative_space` plus `negative_space_alternates`; every gate that judges
"is the room there" reads the same list (`lib.persian_scenes.moment_regions`).
"""
from __future__ import annotations

import jsonschema
import pytest

from lib import persian_assets
from lib.persian_edit_workspace import _declared_region_is_clear
from lib.persian_region_commands import candidate_band_occupancy, declared_negative_space_collisions
from lib.persian_scenes import _NEGATIVE_SPACE_RECTS, audit_scene_plan, moment_regions
import tests.lib.test_persian_gates as gates

_EVENT = gates.TestSceneAudit()._event
_PLAN = gates.TestSceneAudit()._plan


def _grid(y2: int, y1: int = 0):
    frame = {"priority": "hard", "grid": {"x1": 2, "y1": y1, "x2": 8, "y2": y2}}
    return {p: dict(frame) for p in ("start", "middle", "end")}


def _region(name: str) -> dict:
    x, y, w, h = _NEGATIVE_SPACE_RECTS[name]
    return {"x": x + w * 0.2, "y": y + h * 0.2, "w": w * 0.6, "h": h * 0.6, "priority": "hard"}


def _plan_event(**extra) -> dict:
    return {"id": "ve-5", "carries_moment": True, "negative_space": "upper_band", **extra}


def test_moment_regions_lists_the_declared_region_first_without_duplicates() -> None:
    assert moment_regions(_plan_event()) == ["upper_band"]
    assert moment_regions(_plan_event(negative_space_alternates=["centre_band", "upper_band"])) == [
        "upper_band", "centre_band"]


def test_candidate_is_accepted_when_an_alternate_is_clear() -> None:
    # Subject in rows 0-3 fills the upper band but not the centre band (rows 3.3-6.7).
    grid = _grid(y2=3)
    assert candidate_band_occupancy(grid, "upper_band")["occupied"] is True
    result = candidate_band_occupancy(grid, "upper_band", alternates=["centre_band"])
    assert result["occupied"] is False and result["clearAccepted"] == ["centre_band"]


def test_candidate_is_refused_only_when_every_accepted_region_is_occupied() -> None:
    result = candidate_band_occupancy(_grid(y2=7), "upper_band", alternates=["centre_band"])
    assert result["occupied"] is True and result["accepted"] == ["upper_band", "centre_band"]


def test_region_review_collides_only_when_all_accepted_regions_are_occupied() -> None:
    plan = {"beats": [{"visual_events": [_plan_event(negative_space_alternates=["centre_band"])]}]}
    shots = [{"shotId": "shot-5", "visualEventId": "ve-5"}]
    upper_only = [{"shot_id": "shot-5", "avoidRegions": [_region("upper_band")]}]
    both = upper_only + [{"shot_id": "shot-5", "avoidRegions": []}]
    assert declared_negative_space_collisions(plan, shots, upper_only) == []
    rows = [{"shot_id": "shot-5", "avoidRegions": [_region("upper_band"), _region("centre_band")]}]
    collisions = declared_negative_space_collisions(plan, shots, rows)
    assert len(collisions) == 1 and collisions[0]["acceptedRegions"] == ["upper_band", "centre_band"]
    single = {"beats": [{"visual_events": [_plan_event()]}]}
    assert len(declared_negative_space_collisions(single, shots, upper_only)) == 1


def test_edit_gate_agrees_with_region_review() -> None:
    plan = {"beats": [{"visual_events": [_plan_event(negative_space_alternates=["centre_band"])]}]}

    def edit(regions):
        return _declared_region_is_clear(
            {"persian": {"shots": [{"id": "shot-5", "visualEventId": "ve-5", "avoidRegions": regions}]}}, plan
        )

    assert edit([_region("upper_band")]) == []
    problems = edit([_region("upper_band"), _region("centre_band")])
    assert len(problems) == 1 and "'upper_band' or 'centre_band'" in problems[0]


def test_manifest_accepts_any_accepted_region_and_names_them_when_it_is_none() -> None:
    requirement = {"visual_event_id": "ve-5", "carries_moment": True, "negative_space": "upper_band",
                   "negative_space_alternates": ["centre_band"]}
    def problems(observed):
        entry = {"frame_review": {"placement_space": observed}}
        return [p for p in persian_assets._quality_metadata_problems(entry, requirement) if "placement_space" in p]
    assert problems("centre_band") == [] and problems("upper_band") == []
    refused = problems("right_column")
    assert refused and "'upper_band' or 'centre_band'" in refused[0]


def test_plan_audit_refuses_unusable_or_repeated_alternates() -> None:
    def audit(alternates):
        beat = {"id": "beat-1", "duration_seconds": 2.5, "typographic": False, "visual_events": [
            _EVENT(1, carries_moment=True, negative_space="upper_band",
                   negative_space_alternates=alternates,
                   queries=["phone lying on table wide shot plain wall above", "empty table wide shot"])]}
        return [p for p in audit_scene_plan(_PLAN([beat]))["problems"] if "alternates" in p]
    assert audit(["centre_band"]) == []
    assert audit(["left_column"]) and audit(["lower_band"]) and audit(["upper_band"])


def test_scene_plan_schema_accepts_alternates_and_bounds_them() -> None:
    from lib.checkpoint import validate_artifact  # noqa: F401  (import guard for the schema loader)
    import json
    from lib.paths import REPO_ROOT

    schema = json.loads((REPO_ROOT / "schemas/artifacts/scene_plan.schema.json").read_text())
    event = schema["properties"]["beats"]["items"]["properties"]["visual_events"]["items"]["properties"]
    alt = event["negative_space_alternates"]
    jsonschema.validate(["centre_band"], alt)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(["nowhere"], alt)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(["centre_band", "upper_band", "full_frame"], alt)
