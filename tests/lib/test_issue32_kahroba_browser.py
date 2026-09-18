from __future__ import annotations

import os
from pathlib import Path
import unittest

from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]


def _props(*, include_semantic_roles: bool, permute_support_semantics: bool = False) -> dict:
    design = resolve_design({"version": 2, "profile": "film-type", "seed": "issue32-kahroba"})
    segments = [
        {"role": "lead", "semanticRole": "setup", "text": "بزرگ‌ترین اشتباه"},
        {"role": "lead", "semanticRole": "bridge", "text": "دربارهٔ"},
        {"role": "hero", "semanticRole": "subject_hero", "text": "بازی‌های ویدیویی"},
        {"role": "tail", "semanticRole": "connector", "text": "اینه که فکر کنیم فقط"},
        {"role": "tail", "semanticRole": "payoff", "text": "وقت تلف کردنه!"},
    ]
    if permute_support_semantics:
        segments[0]["semanticRole"], segments[1]["semanticRole"] = segments[1]["semanticRole"], segments[0]["semanticRole"]
        segments[3]["semanticRole"], segments[4]["semanticRole"] = segments[4]["semanticRole"], segments[3]["semanticRole"]
    if not include_semantic_roles:
        segments = [{key: value for key, value in segment.items() if key != "semanticRole"} for segment in segments]
    return {
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
            "purpose": "hook-pattern-interrupt",
            "presentation": {"placement": "auto", "emphasis": "none", "recipeId": "editorial-hero-balanced"},
            "segments": segments,
        }],
    }


@unittest.skipUnless(os.environ.get("OPENMONTAGE_BROWSER_TESTS") == "1", "opt-in real browser suite")
class Issue32KahrobaBrowserContract(unittest.TestCase):
    def test_complete_persian_hook_uses_kahroba_and_never_left_orients(self) -> None:
        text = "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!"
        prepared = prepare_film_type_props(_props(include_semantic_roles=True), ROOT / "remotion-composer")
        layout = prepared["filmType"]["moments"]["hook"]
        rows = layout["rows"]

        assert len(rows) == 5, "poster hook must preserve five authored semantic phrases as five rows"
        assert all(row["family"] == "KahrobaEditorial" for row in rows)
        assert " ".join(row["text"] for row in rows) == text
        assert [row["text"] for row in rows] == [
            "بزرگ‌ترین اشتباه", "دربارهٔ", "بازی‌های ویدیویی",
            "اینه که فکر کنیم فقط", "وقت تلف کردنه!",
        ]
        assert layout["placement"] in {"upper-right", "upper-center", "mid-right", "center", "lower-right"}
        assert not layout["placement"].endswith("left")
        assert all(not row["accentWords"] for row in rows), "poster hierarchy uses a semantic hero phrase, not inline word highlighting"
        setup, bridge, subject, connector, payoff = [row["fontSizePx"] for row in rows]
        assert subject > payoff >= setup > bridge, "subject must dominate; setup/payoff are medium; bridge is small"
        assert subject > payoff > connector, "connector must stay small beneath the subject"
        assert abs(bridge - connector) <= 8, "bridge and connector should share the small support scale"
        assert rows[2]["role"] == "hero" and rows[2]["text"] == "بازی‌های ویدیویی"
        assert layout["rect"]["x"] + layout["rect"]["w"] >= 0.87, "RTL hook should sit visually toward the right edge"
        assert prepared["design"]["resolved"]["typography"]["editorial"]["semanticAccent"] == "#FFEA00"

    def test_editorial_poster_stack_refuses_position_only_semantics(self) -> None:
        with self.assertRaisesRegex(ValueError, "semanticRole"):
            prepare_film_type_props(_props(include_semantic_roles=False), ROOT / "remotion-composer")

    def test_support_scale_follows_semantic_role_not_row_position(self) -> None:
        prepared = prepare_film_type_props(
            _props(include_semantic_roles=True, permute_support_semantics=True),
            ROOT / "remotion-composer",
        )
        rows = prepared["filmType"]["moments"]["hook"]["rows"]
        bridge, setup, subject, payoff, connector = [row["fontSizePx"] for row in rows]
        assert subject > payoff >= setup > bridge
        assert subject > payoff > connector
        assert abs(bridge - connector) <= 8
