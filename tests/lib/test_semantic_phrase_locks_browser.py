from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from lib.persian_design import SUPPORTED_FILM_TYPE_215_HASH, resolve_design
from lib.persian_film_type import prepare_film_type_props

ROOT = Path(__file__).resolve().parents[2]


def _pinned_215_design() -> dict:
    profile = json.loads(
        (ROOT / "styles/persian-footage/film-type-2.15.0.json").read_text(encoding="utf-8")
    )
    return {
        "version": 2,
        "profile": "film-type",
        "seed": "semantic-phrase-lock",
        "profileVersion": "2.15.0",
        "contentHash": SUPPORTED_FILM_TYPE_215_HASH,
        "resolved": profile,
    }


def _props(
    text: str,
    *,
    phrase_locks: list[str] | None = None,
    design: dict | None = None,
) -> dict:
    segment = {"role": "hero", "text": text}
    if phrase_locks is not None:
        segment["phraseLocks"] = phrase_locks
    return {
        "format": "vertical",
        "durationSeconds": 14.0,
        "design": design or resolve_design({"version": 2, "profile": "film-type", "seed": "semantic-phrase-lock"}),
        "watermark": {"persianText": "", "latinText": ""},
        "typographicBeats": [],
        "captionMode": "sidecar_only",
        "captions": [],
        "shots": [{"id": "s", "source": "unused.mp4", "startSeconds": 0, "endSeconds": 14, "avoidRegions": []}],
        "moments": [{
            "id": "m",
            "kind": "statement",
            "startSeconds": 4.0,
            "endSeconds": 10.0,
            "presentation": {
                "placement": "auto",
                "emphasis": "inline",
                "recipeId": "editorial-callout-balanced",
                "treatment": "editorial",
            },
            "segments": [segment],
        }],
    }


def _row_texts(prepared: dict) -> list[str]:
    return [row["text"] for row in prepared["filmType"]["moments"]["m"]["rows"]]


@unittest.skipUnless(os.environ.get("OPENMONTAGE_BROWSER_TESTS") == "1", "opt-in real browser suite")
class SemanticPhraseLockBrowserContract(unittest.TestCase):
    def test_multiword_comma_item_is_automatically_kept_on_one_row(self) -> None:
        prepared = prepare_film_type_props(
            _props("توجه، درک فضایی، حافظه"),
            ROOT / "remotion-composer",
        )
        layout = prepared["filmType"]["moments"]["m"]
        rows = _row_texts(prepared)
        self.assertTrue(any("درک فضایی" in row for row in rows), rows)
        self.assertFalse(any(row.rstrip("،").endswith("درک") for row in rows), rows)
        self.assertFalse(any(row.lstrip().startswith("فضایی") for row in rows), rows)
        self.assertIn(len(rows), {2, 3}, rows)
        self.assertGreaterEqual(
            min(row["fontSizePx"] for row in layout["rows"]),
            98,
            "a semantic list must reflow at display size instead of shrinking into one small line",
        )

    def test_explicit_phrase_lock_keeps_non_list_semantic_unit_intact(self) -> None:
        prepared = prepare_film_type_props(
            _props(
                "تمرین‌های روزانه سلامت روان را بهتر می‌کنند",
                phrase_locks=["سلامت روان"],
            ),
            ROOT / "remotion-composer",
        )
        rows = _row_texts(prepared)
        self.assertTrue(any("سلامت روان" in row for row in rows), rows)
        self.assertFalse(any(row.rstrip("،").endswith("سلامت") for row in rows), rows)
        self.assertFalse(any(row.lstrip().startswith("روان") for row in rows), rows)

    def test_renderer_refuses_phrase_lock_not_present_in_segment(self) -> None:
        with self.assertRaisesRegex(ValueError, "phraseLocks"):
            prepare_film_type_props(
                _props("سلامت روان مهم است", phrase_locks=["کنترل توجه"]),
                ROOT / "remotion-composer",
            )

    def test_pinned_215_does_not_infer_new_comma_list_phrase_locks(self) -> None:
        prepared = prepare_film_type_props(
            _props(
                "توجه دیداری، درک فضایی پیچیده، حافظه کاری",
                design=_pinned_215_design(),
            ),
            ROOT / "remotion-composer",
        )
        self.assertEqual(
            _row_texts(prepared),
            ["توجه دیداری، درک فضایی", "پیچیده، حافظه کاری"],
        )


if __name__ == "__main__":
    unittest.main()
