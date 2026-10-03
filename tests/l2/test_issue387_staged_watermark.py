"""#387 increment 4: under v3_staged the brand (stage 4) never blocks.

Real Chromium + Film Type fonts (opt-in L2; CI uses the licensed 2.16 profile, local
runs may pin ``OPENMONTAGE_L2_FILM_TYPE_PIN=2.15.0``). Only two constraints remain:
inside the watermark safe zone and the text distance. Faces/subjects are not
obstacles. Where the planner leaves the brand below its coverage floor, the
in-safe-zone anchor farthest from the painted text is used and recorded.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.persian_film_type import FilmTypePreflightError, prepare_film_type_props
from tests.l2.test_issue387_staged_text_adapts import ROOT, _design

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)

DURATION = 23.5
SEGMENTS = [{"role": "lead", "text": "جالب‌ترین نتیجه"},
            {"role": "hero", "text": "بیشترین تمایل به ادامهٔ رابطه"}]


def _props(*, staged: bool, crowded: bool, face: bool = True) -> dict:
    presentation = {"placement": "upper-center"} if crowded else None
    moments = [{"id": f"m{i}", "kind": "statement", "startSeconds": s, "endSeconds": s + 5.0,
                "segments": SEGMENTS, **({"presentation": presentation} if presentation else {})}
               for i, s in enumerate([0.5, 6.4, 12.3, 18.2])]
    props = {
        "format": "vertical", "durationSeconds": DURATION, "design": _design(),
        "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        "typographicBeats": [], "captionMode": "hybrid",
        "captions": [{"id": f"c{i}", "startSeconds": i * 3.3, "endSeconds": i * 3.3 + 3.2,
                      "text": "بعد، یا دو روز بعد.", "lines": ["بعد، یا دو روز بعد."]} for i in range(7)],
        # A full-frame hard face: never an obstacle for the brand.
        "shots": [{"id": "s", "source": "unused.mp4", "startSeconds": 0.0, "endSeconds": DURATION,
                   "avoidRegions": [{"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "priority": "hard",
                                     "startSeconds": 0.0, "endSeconds": DURATION}] if face else []}],
        "moments": moments,
    }
    if staged:
        props["pipelineProfile"] = "v3_staged"
    return props


def _prepare(props: dict, tmp_path: Path) -> dict:
    return prepare_film_type_props(props, ROOT / "remotion-composer", scratch_dir=tmp_path)


def _safe(prepared: dict) -> dict:
    resolved = prepared["design"]["resolved"]
    areas = (resolved.get("watermark") or {}).get("safeAreas") or {}
    return areas.get("vertical") or resolved["formats"]["vertical"]["safeArea"]


def _coverage(plan: list[dict]) -> float:
    return sum(slot["endSeconds"] - slot["startSeconds"] for slot in plan) / DURATION


@pytest.mark.parametrize("crowded", [False, True])
def test_the_brand_never_blocks_and_stays_in_the_safe_zone(tmp_path: Path, crowded: bool) -> None:
    prepared = _prepare(_props(staged=True, crowded=crowded), tmp_path)
    plan = prepared["watermarkPlan"]
    assert plan, "the brand is planned"
    safe = _safe(prepared)
    left, right = safe.get("left", safe.get("side")), safe.get("right", safe.get("side"))
    for slot in plan:
        rect = slot["rect"]
        assert rect["x"] >= left - 1e-6 and rect["x"] + rect["w"] <= 1 - right + 1e-6, slot
        assert rect["y"] >= safe["top"] - 1e-6 and rect["y"] + rect["h"] <= 1 - safe["bottom"] + 1e-6, slot
    floor = prepared["design"]["resolved"]["watermark"].get("minCoverageRatio", 0.0)
    warnings = prepared["filmType"]["warnings"]
    assert _coverage(plan) + 1e-6 >= floor or any("watermark-coverage-below-floor" in w for w in warnings)
    filled = prepared["filmType"]["stagedWatermark"]["filledSlots"]
    for item in filled:
        assert any(slot["zone"] == item["zone"] and slot["startSeconds"] == item["startSeconds"]
                   and slot["reason"].startswith("v3-farthest-from-text") for slot in plan)


def test_v3_keeps_every_slot_the_planner_chose(tmp_path: Path) -> None:
    try:
        v2 = _prepare(_props(staged=False, crowded=False, face=False), tmp_path)
    except FilmTypePreflightError:
        pytest.skip("v2 cannot place this text; covered by the crowded case")
    v3 = _prepare(_props(staged=True, crowded=False, face=False), tmp_path)
    planned = [slot for slot in v3["watermarkPlan"] if not slot["reason"].startswith("v3-farthest-from-text")]
    assert planned == v2["watermarkPlan"]


@pytest.mark.parametrize("crowded", [False, True])
def test_v3_fills_only_when_the_planner_leaves_the_brand_below_its_floor(tmp_path: Path, crowded: bool) -> None:
    # Font-independent: whether the planner meets the floor depends on the
    # measured Film Type profile (2.15 locally, licensed 2.16 in CI). The
    # invariant is what v3 does in either case.
    v3 = _prepare(_props(staged=True, crowded=crowded), tmp_path)
    plan = v3["watermarkPlan"]
    planned = [slot for slot in plan if not slot["reason"].startswith("v3-farthest-from-text")]
    floor = v3["design"]["resolved"]["watermark"].get("minCoverageRatio", 0.0)
    filled = v3["filmType"]["stagedWatermark"]["filledSlots"]
    warnings = v3["filmType"]["warnings"]
    if _coverage(planned) + 1e-6 < floor:
        assert filled, "below the floor, v3 must use the farthest in-safe-zone anchor"
        assert any("watermark-farthest-from-text" in w for w in warnings)
    else:
        assert filled == [], "the planner met the floor; nothing is added"
        assert not any("watermark-farthest-from-text" in w for w in warnings)
