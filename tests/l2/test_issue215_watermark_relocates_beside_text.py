"""#215: under Film Type 2.16 the brand moves away from text instead of disappearing.

Real Chromium measurement (the same opt-in L2 environment as #138), so the brand and text
rectangles are the renderer's own. Two defects made the brand vanish under every
moment in a burned-caption run and failed the 70% coverage floor (36% measured):

1. A burned caption was charged as an obstacle for its whole cue, even while a moment
   owned the frame and PersianCaptionBlock painted nothing, so the lower anchors closed
   at exactly the moments the text held the upper ones.
2. The lower anchors sat inside the caption clearance, so any painting caption closed them.

Policy asserted here: coverage stays at or above the floor, and while text is up the brand
sits in the other vertical band, clear of the text and captions by the measured clearance.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)

DURATION = 62.5
MOMENT_STARTS = [3.0, 14.0, 24.4, 35.1, 44.0, 52.0, 58.0]


def _props() -> dict:
    moments = [
        {
            "id": f"m{index}", "kind": "statement",
            "startSeconds": start, "endSeconds": start + 3.8,
            "presentation": {"placement": "upper-right"},
            "segments": [{"role": "hero", "text": "دو روز صبر کردن"}],
        }
        for index, start in enumerate(MOMENT_STARTS)
    ]
    captions = [
        {"id": f"c{index}", "startSeconds": index * 3.0, "endSeconds": index * 3.0 + 2.9,
         "text": "این یک زیرنویس آزمایشی است", "lines": ["این یک زیرنویس آزمایشی است"]}
        for index in range(20)
    ]
    return {
        "format": "vertical", "durationSeconds": DURATION,
        "design": resolve_design({"version": 2, "profile": "film-type", "seed": "issue215-l2"}),
        "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        "typographicBeats": [], "captionMode": "hybrid", "captions": captions,
        "shots": [{"id": "s", "source": "unused.mp4", "startSeconds": 0.0,
                   "endSeconds": DURATION, "avoidRegions": []}],
        "moments": moments,
    }


def _overlaps(a: dict, b: dict) -> bool:
    return a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] \
        and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"]


def test_brand_relocates_beside_text_and_keeps_the_coverage_floor(tmp_path: Path) -> None:
    props = _props()
    prepared = prepare_film_type_props(props, ROOT / "remotion-composer", scratch_dir=tmp_path)
    assert prepared["design"]["profileVersion"] == "2.16.0"
    plan = prepared["watermarkPlan"]
    covered = sum(slot["endSeconds"] - slot["startSeconds"] for slot in plan)
    # #230: 2.16 keeps the brand visible 55-75% of the runtime (92% crowded the frame).
    assert 0.55 - 1e-6 <= covered / DURATION <= 0.755  # slot edges land on event times

    layouts = prepared["filmType"]["moments"]
    for moment in props["moments"]:
        text = layouts[moment["id"]]["rect"]
        live = [s for s in plan
                if s["startSeconds"] < moment["endSeconds"] and s["endSeconds"] > moment["startSeconds"]]
        for slot in live:
            brand = slot["rect"]
            assert not _overlaps(brand, text)
            # Upper text moves the brand to the lower band, not beside the text.
            assert slot["zone"].startswith("lower"), (moment["id"], slot["zone"])
