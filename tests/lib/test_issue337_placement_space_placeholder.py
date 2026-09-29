"""#337: a review that wrote placement_space "none" for a non-carrier event was immutable
and made the manifest schema refuse the whole build (2026-09-29 run, ve-8)."""
from __future__ import annotations

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_asset_workspace import PersianAssetWorkspaceError, _manifest_evidence, _validate_review


def _review(**frame_extra) -> dict:
    return {
        "frame_review": {"start": True, "middle": True, "end": True, "observed": "a crowd", **frame_extra},
        "shows_subject": True, "human_presence": True, "affect_match": True,
        "staged_stock_risk": "low", "relevance_reason": "matches", "selection_reason": "best",
        "geometry_review": {"crop_safe": True, "observed": "fits"},
    }


def test_new_review_refuses_a_placeholder_and_says_to_omit_it() -> None:
    with pytest.raises(PersianAssetWorkspaceError, match="omit the field"):
        _validate_review(_review(placement_space="none"))
    assert _validate_review(_review(placement_space="upper_band"))["frame_review"]["placement_space"] == "upper_band"
    assert "placement_space" not in _validate_review(_review())["frame_review"]


def test_an_already_recorded_placeholder_is_left_out_of_the_manifest_evidence() -> None:
    candidate = {"context": {"visualEventId": "ve-8"}, "review": _review(placement_space="none")}
    frame = _manifest_evidence(candidate)["frame_review"]
    assert "placement_space" not in frame and frame["observed"] == "a crowd"
    real = {"context": {"visualEventId": "ve-4"}, "review": _review(placement_space="upper_band")}
    assert _manifest_evidence(real)["frame_review"]["placement_space"] == "upper_band"
