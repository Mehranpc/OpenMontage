"""#335: BAND_OCCUPIED must only offer regions a moment can actually be laid out in.

The 2026-09-29 run was told a phone-occupied upper_band footage "leaves left_column,
right_column and lower_band clear". In Film Type vertical none of those can host type
(columns are narrower than the narrowest recipe column, the lower band is the caption
reserve), and the plan audit refuses them, so the hint sent the run to a declaration
that fails three phases later.
"""
from __future__ import annotations

import pytest

from lib.persian_region_commands import candidate_band_occupancy
from lib.persian_scenes import (
    negative_space_unserviceable_reason,
    serviceable_negative_space_regions,
)


def _grid(**frame):
    return {position: dict(frame) for position in ("start", "middle", "end")}


def test_vertical_serviceable_regions_are_the_bands_and_the_full_frame() -> None:
    assert serviceable_negative_space_regions("vertical") == {"upper_band", "centre_band", "full_frame"}


@pytest.mark.parametrize("region", ["left_column", "right_column", "lower_band"])
def test_unserviceable_regions_say_why(region: str) -> None:
    assert negative_space_unserviceable_reason(region, "vertical")


def test_landscape_keeps_the_lower_band() -> None:
    assert "lower_band" in serviceable_negative_space_regions("landscape")


def test_occupied_upper_band_offers_only_a_serviceable_way_out() -> None:
    # Subject fills the upper band and the middle; only the very bottom is empty.
    result = candidate_band_occupancy(
        _grid(priority="hard", grid={"x1": 0, "y1": 0, "x2": 10, "y2": 6}), "upper_band"
    )
    assert result["occupied"] is True
    assert result["clearRegions"] == []  # lower_band is empty but is the caption reserve


def test_a_phone_left_of_frame_leaves_centre_band_as_the_offered_way_out() -> None:
    result = candidate_band_occupancy(
        _grid(priority="hard", grid={"x1": 0, "y1": 0, "x2": 10, "y2": 3}), "upper_band"
    )
    assert result["occupied"] is True
    assert result["clearRegions"] == ["centre_band"]
    assert not {"left_column", "right_column", "lower_band"} & set(result["clearRegions"])


def test_landscape_format_still_offers_the_lower_band() -> None:
    result = candidate_band_occupancy(
        _grid(priority="hard", grid={"x1": 0, "y1": 0, "x2": 10, "y2": 3}), "upper_band", fmt="landscape"
    )
    assert "lower_band" in result["clearRegions"]


def test_reconcile_plan_refuses_a_region_the_plan_audit_would_refuse(tmp_path) -> None:
    from lib import persian_video_workflow as workflow
    from tests.lib.test_issue224_plan_reconcile import BASE, _run_at_acquire

    _run_at_acquire(tmp_path)
    for region in ("left_column", "lower_band"):
        with pytest.raises(workflow.PersianVideoWorkflowError, match="only moves the failure later"):
            workflow.reconcile_scene_plan(
                "run", [{"visual_event_id": "event-1", "set": {"negative_space": region}}],
                reason="x", pipeline_dir=tmp_path, now=BASE,
            )
