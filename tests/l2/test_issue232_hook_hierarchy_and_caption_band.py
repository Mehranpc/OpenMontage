"""#232: the poster hook keeps its hierarchy wherever it is placed, and the brand stays
out of the burned-caption band while a caption paints.

Real Chromium + the licensed Kahroba font (opt-in L2, run in CI). Mehran's review of the
re-render: moved off the face to mid-right, the hook collapsed from a three-row poster
(hero / tail / tail) to hero + one full-width tail; and the brand sat right above the
caption panel."""

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


def _hook_props(duration: float = 30.0, captions: bool = False) -> dict:
    return {
        "format": "vertical", "durationSeconds": duration,
        "design": resolve_design({"version": 2, "profile": "film-type", "seed": "issue232-l2"}),
        "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        "typographicBeats": [],
        "captionMode": "hybrid" if captions else "sidecar_only",
        "captions": [
            {"id": f"c{i}", "startSeconds": 5.0 + i * 3.0, "endSeconds": 5.0 + i * 3.0 + 2.9,
             "text": "طرف مقابل یا بلافاصله پیام می‌داد", "lines": ["طرف مقابل یا بلافاصله پیام می‌داد"]}
            for i in range(8)
        ] if captions else [],
        "shots": [{
            "id": "s1", "source": "unused.mp4", "startSeconds": 0.0, "endSeconds": duration,
            # The re-render's face: upper-middle of the frame, marked hard.
            "avoidRegions": [{"x": 0.3, "y": 0.1, "w": 0.45, "h": 0.25, "priority": "hard",
                              "startSeconds": 0.0, "endSeconds": duration}],
        }],
        "moments": [{
            "id": "m-hook", "kind": "hook", "startSeconds": 0.0, "endSeconds": 5.0,
            "segments": [{"role": "hero", "text": "صبحِ روز بعد"},
                         {"role": "tail", "text": "زمانِ پیام بعد از قرار اول"}],
        }],
    }


def test_the_hook_keeps_its_poster_hierarchy_off_the_face(tmp_path: Path) -> None:
    prepared = prepare_film_type_props(_hook_props(), ROOT / "remotion-composer", scratch_dir=tmp_path)
    layout = prepared["filmType"]["moments"]["m-hook"]
    rect = layout["rect"]
    assert rect["y"] >= 0.35 - 1e-6 or rect["x"] >= 0.75, "the hook moved off the marked face"
    rows = [row for row in layout["rows"] if row["role"] != "brand"]
    hero = [row for row in rows if row["role"] == "hero"]
    tail = [row for row in rows if row["role"] == "tail"]
    assert len(rows) >= 3, [row["text"] for row in rows]
    assert max(row["widthPx"] for row in tail) <= max(row["widthPx"] for row in hero) * 1.12


def test_the_brand_stays_out_of_the_caption_band_while_captions_paint(tmp_path: Path) -> None:
    prepared = prepare_film_type_props(
        _hook_props(duration=30.0, captions=True), ROOT / "remotion-composer", scratch_dir=tmp_path
    )
    captions = prepared["captions"]
    for slot in prepared["watermarkPlan"]:
        if not slot["zone"].startswith("lower"):
            continue
        live = [c for c in captions if c["startSeconds"] < slot["endSeconds"] and c["endSeconds"] > slot["startSeconds"]]
        assert not live, (slot["zone"], slot["startSeconds"], slot["endSeconds"])


def test_region_review_hook_screen_agrees_with_real_placement(tmp_path: Path) -> None:
    """#229: when the region-review screen reports a clear hook zone, the real Film Type
    placement finds a spot clear of the same hard regions (the screen is not optimistic)."""
    from lib.persian_region_commands import opening_hook_placement

    face = {"x": 0.3, "y": 0.1, "w": 0.45, "h": 0.25, "priority": "hard",
            "startSeconds": 0.0, "endSeconds": 30.0}
    finding = opening_hook_placement(
        [{"shotId": "s1", "timeline": {"startSeconds": 0.0, "endSeconds": 30.0}}],
        [{"shot_id": "s1", "avoidRegions": [face]}],
    )
    assert finding["feasible"] is True
    prepared = prepare_film_type_props(_hook_props(), ROOT / "remotion-composer", scratch_dir=tmp_path)
    placed = prepared["filmType"]["moments"]["m-hook"]["placement"]
    assert placed in finding["clearZones"], (placed, finding["clearZones"])
