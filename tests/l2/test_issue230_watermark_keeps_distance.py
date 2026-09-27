"""#230: under Film Type 2.16 the brand takes the anchor farthest from the text it shares
the screen with, and never sits right under a moment when the opposite corner is free.

Real Chromium measurement (opt-in L2, run in CI with the licensed font)."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]
DURATION = 40.0

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)


def _props() -> dict:
    # The screenshot-3 moment exactly: auto placement settles on a right-aligned block.
    moments = [{
        "id": f"m{i}", "kind": "statement", "startSeconds": s, "endSeconds": s + 4.978,
        "segments": [{"role": "lead", "text": "جالب‌ترین نتیجه"},
                     {"role": "hero", "text": "بیشترین تمایل به ادامهٔ رابطه"}],
    } for i, s in enumerate([6.0, 16.0, 26.0])]
    captions = [{"id": f"c{i}", "startSeconds": i * 3.0, "endSeconds": i * 3.0 + 2.9,
                 "text": "بعد، یا دو روز بعد.", "lines": ["بعد، یا دو روز بعد."]} for i in range(13)]
    return {
        "format": "vertical", "durationSeconds": DURATION,
        "design": resolve_design({"version": 2, "profile": "film-type", "seed": "issue230-l2"}),
        "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        "typographicBeats": [], "captionMode": "hybrid", "captions": captions,
        "shots": [{"id": "s", "source": "unused.mp4", "startSeconds": 0.0,
                   "endSeconds": DURATION, "avoidRegions": []}],
        "moments": moments,
    }


def _gap_px(a: dict, b: dict) -> float:
    dx = max(0.0, b["x"] - (a["x"] + a["w"]), a["x"] - (b["x"] + b["w"])) * 1080
    dy = max(0.0, b["y"] - (a["y"] + a["h"]), a["y"] - (b["y"] + b["h"])) * 1920
    return math.hypot(dx, dy)


def test_brand_never_stacks_under_a_right_aligned_block_and_stays_in_range(tmp_path: Path) -> None:
    props = _props()
    prepared = prepare_film_type_props(props, ROOT / "remotion-composer", scratch_dir=tmp_path)
    assert prepared["design"]["profileVersion"] == "2.16.0"
    plan = prepared["watermarkPlan"]
    coverage = sum(s["endSeconds"] - s["startSeconds"] for s in plan) / DURATION
    assert 0.55 - 1e-6 <= coverage <= 0.755, coverage  # slot edges land on event times
    layouts = prepared["filmType"]["moments"]
    for moment in props["moments"]:
        text = layouts[moment["id"]]["rect"]
        for slot in plan:
            if slot["startSeconds"] < moment["endSeconds"] and slot["endSeconds"] > moment["startSeconds"]:
                brand = slot["rect"]
                centre = brand["x"] + brand["w"] / 2
                stacked = text["x"] <= centre <= text["x"] + text["w"]
                assert not stacked or _gap_px(brand, text) >= 320, (moment["id"], slot["zone"], text)
