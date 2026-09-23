"""Issue 81 regression for exact-text non-hook subject-wrap recovery."""
from __future__ import annotations

import unittest
from pathlib import Path

from lib.persian_brand import exact_text_record
from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props


ROOT = Path(__file__).resolve().parents[2]


class Issue81ExactNonHookSubjectWrap(unittest.TestCase):
    @staticmethod
    def _overlaps(a: dict, b: dict) -> bool:
        return (
            a["x"] < b["x"] + b["w"]
            and a["x"] + a["w"] > b["x"]
            and a["y"] < b["y"] + b["h"]
            and a["y"] + a["h"] > b["y"]
        )

    def _props(self, *, exact: bool) -> dict:
        visible = "در این مطالعه، ۵۴۳ نفر"
        moment = {
            "id": "moment-02-sample",
            "kind": "figure",
            "startSeconds": 0.0,
            "endSeconds": 5.0,
            "presentation": {"placement": "auto"},
            "segments": [
                {"role": "lead", "text": "در این مطالعه،"},
                {"role": "hero", "text": "۵۴۳ نفر"},
            ],
        }
        if exact:
            moment["exactText"] = exact_text_record(visible)
        return {
            "format": "vertical",
            "durationSeconds": 20.0,
            "design": resolve_design(
                {"version": 2, "profile": "film-type", "seed": "issue81-nonhook"}
            ),
            "watermark": {"persianText": "", "latinText": ""},
            "typographicBeats": [],
            "captionMode": "sidecar_only",
            "captions": [],
            "shots": [
                {
                    "id": "beat-03-event-01",
                    "source": "unused.mp4",
                    "startSeconds": 0.0,
                    "endSeconds": 20.0,
                    "visualComplexity": "busy",
                    "avoidRegions": [
                        {"x": 0.37, "y": 0.24, "w": 0.32, "h": 0.27, "priority": "hard"},
                        {"x": 0.57, "y": 0.47, "w": 0.30, "h": 0.25, "priority": "hard"},
                        {"x": 0.17, "y": 0.00, "w": 0.82, "h": 0.78, "priority": "soft"},
                    ],
                }
            ],
            "moments": [moment],
        }

    def _prepare(self, props: dict) -> dict:
        return prepare_film_type_props(props, ROOT / "remotion-composer")

    def test_exact_figure_can_use_scoped_subject_wrap_without_copy_or_region_change(self) -> None:
        props = self._props(exact=True)
        prepared = self._prepare(props)
        layout = prepared["filmType"]["moments"]["moment-02-sample"]

        self.assertTrue(layout.get("subjectWrap"))
        self.assertEqual(layout["placement"], "subject-wrap")
        self.assertEqual(layout["subjectSafety"], "checked-against-supplied-regions")
        self.assertEqual(
            " ".join(row["text"] for row in layout["rows"]),
            "در این مطالعه، ۵۴۳ نفر",
        )
        self.assertEqual(prepared["shots"][0]["avoidRegions"], props["shots"][0]["avoidRegions"])
        self.assertEqual(prepared["moments"][0]["exactText"], props["moments"][0]["exactText"])

        margin = 12
        motion = 18
        width, height = 1080, 1920
        ink_pad = 12
        anchor = layout["widthPx"] - ink_pad
        hard = props["shots"][0]["avoidRegions"][:2]
        for row in layout["rows"]:
            row_anchor = anchor + row.get("offsetXPx", 0)
            collision = {
                "x": layout["rect"]["x"] + (row_anchor - row["widthPx"] - margin) / width,
                "y": layout["rect"]["y"] + (row["baselinePx"] - row["abovePx"] - margin) / height,
                "w": (row["widthPx"] + 2 * margin) / width,
                "h": (row["abovePx"] + row["belowPx"] + motion + 2 * margin) / height,
            }
            self.assertFalse(any(self._overlaps(collision, region) for region in hard), row["text"])

    def test_non_exact_figure_keeps_historical_non_wrap_behavior(self) -> None:
        with self.assertRaisesRegex(ValueError, "no curated adaptive editorial recipe fits"):
            self._prepare(self._props(exact=False))
