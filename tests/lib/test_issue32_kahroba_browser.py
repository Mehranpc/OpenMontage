from __future__ import annotations

import os
from pathlib import Path
import unittest

from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("OPENMONTAGE_BROWSER_TESTS") == "1", "opt-in real browser suite")
class Issue32KahrobaBrowserContract(unittest.TestCase):
    def test_complete_persian_hook_uses_kahroba_and_never_left_orients(self) -> None:
        text = "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!"
        design = resolve_design({"version": 2, "profile": "film-type", "seed": "issue32-kahroba"})
        props = {
            "format": "vertical",
            "durationSeconds": 12.0,
            "design": design,
            "watermark": {"persianText": "", "latinText": ""},
            "typographicBeats": [],
            "captionMode": "sidecar_only",
            "captions": [],
            "shots": [{"id": "s", "source": "unused.mp4", "startSeconds": 0, "endSeconds": 12, "avoidRegions": []}],
            "moments": [{
                "id": "hook",
                "kind": "hook",
                "startSeconds": 0.0,
                "endSeconds": 5.0,
                "presentation": {"placement": "auto", "emphasis": "inline", "recipeId": "editorial-hero-balanced"},
                "segments": [{"role": "hero", "text": text, "accentWords": ["بازی‌های", "ویدیویی"]}],
            }],
        }

        prepared = prepare_film_type_props(props, ROOT / "remotion-composer")
        layout = prepared["filmType"]["moments"]["hook"]
        hero_rows = [row for row in layout["rows"] if row["role"] == "hero"]

        assert 2 <= len(hero_rows) <= 5
        assert all(row["family"] == "KahrobaEditorial" for row in hero_rows)
        assert " ".join(row["text"] for row in hero_rows) == text
        assert layout["placement"] in {"upper-right", "upper-center", "mid-right", "center", "lower-right"}
        assert not layout["placement"].endswith("left")
        accent_rows = [row for row in hero_rows if row["accentWords"]]
        assert len(accent_rows) == 1, "semantic accent belongs only to the row containing the accented phrase"
        sizes = [row["fontSizePx"] for row in hero_rows]
        assert max(sizes) - min(sizes) >= 16, "poster hook needs visible typographic hierarchy, not four equal rows"
        assert accent_rows[0]["fontSizePx"] == max(sizes), "the strongest semantic phrase must carry the largest display size"
        assert layout["rect"]["x"] + layout["rect"]["w"] >= 0.87, "RTL hook should sit visually toward the right edge"
        assert "بازی‌های ویدیویی" in accent_rows[0]["text"]
        assert all(word in accent_rows[0]["text"] for word in accent_rows[0]["accentWords"])
        assert prepared["design"]["resolved"]["typography"]["editorial"]["semanticAccent"] == "#FFEA00"
