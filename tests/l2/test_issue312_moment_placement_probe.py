"""#312: whether a carrier's moment can be placed is decided by the browser, before edit.

f418063 run: moment-3 (`۵۴۳ نفر` + tail) on shot-4 cost four edit candidates and a cycle
before `no safe measured placement remains`. The shot's reviewed regions were known at
region review. The Film Type prepass needs only props (no media, no render), so the same
`placeMoment` can answer at region review. This test pins that the prepass refuses that
exact moment on those exact regions, and places it once the hard face region is gone,
so the region-review probe relies on the renderer's own decision, not a model of it.
"""
from __future__ import annotations

import os

import pytest

from lib.persian_design import resolve_design
from lib.persian_film_type import FilmTypePreflightError, prepare_film_type_props
from tools.video.persian_compose import _composer_dir

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)

# shot-4's regions from the run's last draft (edit10): face hard, crowd + silhouette soft.
SHOT4_REGIONS = [
    {"x": 0.0, "y": 0.42, "w": 1.0, "h": 0.58, "priority": "soft"},
    {"x": 0.0, "y": 0.15, "w": 0.35, "h": 0.55, "priority": "soft"},
    {"x": 0.5, "y": 0.42, "w": 0.2, "h": 0.18, "priority": "hard"},
]
MOMENT3 = {
    "id": "moment-3", "kind": "figure", "startSeconds": 1.9, "endSeconds": 6.0,
    "segments": [{"role": "hero", "text": "۵۴۳ نفر"}, {"role": "tail", "text": "یک قرار اول را تصور کردند"}],
    "anchorText": "۵۴۳ نفر تصور کردند",
    "presentation": {"recipeId": "editorial-hero-compact"},
}


def _props(regions: list[dict]) -> dict:
    return {
        "format": "vertical", "durationSeconds": 6.03,
        "design": resolve_design({"version": 2, "profile": "film-type", "seed": "issue312-l2"}),
        "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        "typographicBeats": [], "captionMode": "hybrid", "captions": [],
        "shots": [{"id": "shot-4", "source": "unused.mp4", "startSeconds": 0.0, "endSeconds": 6.03,
                   "avoidRegions": [{**r, "startSeconds": 0.0, "endSeconds": 6.03} for r in regions]}],
        "moments": [MOMENT3],
    }


def test_the_real_moment_is_refused_on_the_real_regions(tmp_path) -> None:
    with pytest.raises(FilmTypePreflightError) as excinfo:
        prepare_film_type_props(_props(SHOT4_REGIONS), _composer_dir(), scratch_dir=tmp_path)
    assert excinfo.value.code == "ASSET_SELECTION_HARD_REGION_COLLISION", str(excinfo.value)


def test_the_same_moment_places_without_the_hard_face(tmp_path) -> None:
    soft_only = [r for r in SHOT4_REGIONS if r["priority"] == "soft"]
    prepared = prepare_film_type_props(_props(soft_only), _composer_dir(), scratch_dir=tmp_path)
    assert prepared["moments"][0].get("layoutGeometry")
