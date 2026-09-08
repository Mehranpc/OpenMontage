"""Dedicated Stage-B contracts for opt-in Persian V2."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from lib.persian_design import resolve_design, resolve_watermark_plan, validate_presentation
from tools.video.persian_compose import PersianCompose


def moment(placement="auto", treatment="editorial", motion="soft-reveal"):
    return {"id":"m", "kind":"statement", "segments":[{"role":"hero","text":"یک پیام کوتاه"}],
            "presentation":{"treatment":treatment,"placement":placement,"motion":motion,"emphasis":"none"}}


def test_invalid_placement_rejected_before_render():
    with pytest.raises(ValueError, match="placement"):
        validate_presentation(moment("diagonal"), 0)

@pytest.mark.parametrize("key,value", [("treatment","figure-focus"),("motion","bounce"),("emphasis","sized"),("contrastMode","sepia")])
def test_invalid_presentation_rejected(key, value):
    p = moment(); p["presentation"][key] = value
    with pytest.raises(ValueError): validate_presentation(p, 0)


def test_snapshot_is_consumed_and_change_is_visible():
    raw={"version":2,"profile":"quiet-editorial","seed":"stable"}
    one=resolve_design(raw); two=resolve_design({**raw,"seed":"different"})
    assert one["resolved"] == two["resolved"]
    assert one["seed"] != two["seed"]
    assert one["contentHash"] == hashlib_sha()


def hashlib_sha():
    import hashlib
    path=Path(__file__).parents[2]/"styles/persian-footage/v2.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_watermark_seeded_deterministic_and_uses_safe_area_policy():
    kwargs=dict(duration_seconds=20, format="landscape", text_rects=[{"x":.05,"y":.4,"w":.4,"h":.2}], safe_area={"top":.1,"bottom":.15,"side":.1},
                motion_policy={"maxRelocations":1,"minDwellSeconds":6,"transition":"relocate-fade"}, lockup_size={"w":0.2,"h":0.03,"measured":True})
    a=resolve_watermark_plan(seed="abc", **kwargs); b=resolve_watermark_plan(seed="abc", **kwargs)
    assert a == b and len(a) == 2
    assert a[1]["transition"] == "relocate-fade"
    assert all(e["rect"]["y"] >= .1 for e in a)


def test_watermark_avoid_regions_and_unknown_placement_have_explicit_behavior():
    plan=resolve_watermark_plan(duration_seconds=8, format="vertical", seed="x", text_rects=[],
        avoid_regions=[{"x":.07,"y":.7,"w":.4,"h":.2}], safe_area={"top":.08,"bottom":.2,"side":.08},
        lockup_size={"w":0.2,"h":0.03,"measured":True})
    assert plan and not (plan[0]["rect"]["x"] < .47 and plan[0]["rect"]["y"] > .7)


def test_watermark_requires_real_measurement():
    with pytest.raises(ValueError, match="loaded-font raster"):
        from lib.persian_design import derive_lockup_size
        derive_lockup_size()


def test_legacy_without_design_remains_legacy():
    assert resolve_design(None) is None
    assert resolve_design({"seed":"old"}) is None


def test_v2_palette_uses_pathway_brand_and_is_snapshot_hashed():
    profile = json.loads((Path(__file__).parents[2] / "styles/persian-footage/v2.json").read_text())
    assert profile["palette"]["electricBlue"] == "#1789FC"
    assert profile["palette"]["boneWhite"] == "#F0EDE6"
    assert profile["typography"]["ink"] == "#F0EDE6"
    assert profile["typography"]["accent"] == "#1789FC"
    snapshot = resolve_design({"version": 2, "profile": "quiet-editorial", "seed": "frozen"})
    assert snapshot["contentHash"] == hashlib_sha()
    assert snapshot["resolved"] == profile


def test_v2_contrast_mode_accepts_light_and_rejects_unknown():
    validate_presentation({**moment(), "presentation": {**moment()["presentation"], "contrastMode": "light"}}, 0)
    with pytest.raises(ValueError, match="contrastMode"):
        validate_presentation({**moment(), "presentation": {**moment()["presentation"], "contrastMode": "sepia"}}, 0)


def test_v2_empty_schedule_is_allowed_but_legacy_empty_is_refused():
    assert PersianCompose._build_moments({"moments": []}, 10, v2=True) == []
    with pytest.raises(ValueError, match="Legacy"):
        PersianCompose._build_moments({"moments": []}, 10, v2=False)


def test_watermark_oversized_lockup_fails_safe_area():
    with pytest.raises(ValueError, match="does not fit"):
        resolve_watermark_plan(duration_seconds=20, format="vertical", seed="x", text_rects=[],
            safe_area={"top": .1, "bottom": .2, "side": .1},
            lockup_size={"w": .81, "h": .04, "measured": True})


def test_watermark_plan_never_uses_outside_safe_area():
    plan = resolve_watermark_plan(
        duration_seconds=20, format="vertical", seed="safe",
        text_rects=[], safe_area={"top": .1, "bottom": .2, "side": .1},
        lockup_size={"w": .2, "h": .04, "measured": True},
    )
    assert plan
    for entry in plan:
        rect = entry["rect"]
        assert rect["x"] >= .1 and rect["x"] + rect["w"] <= .9
        assert rect["y"] >= .1 and rect["y"] + rect["h"] <= .8
