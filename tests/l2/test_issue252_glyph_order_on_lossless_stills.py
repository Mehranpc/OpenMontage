"""#252: glyph order is verified on lossless stills of the real 2.16 composition.

Real Chromium + the licensed Kahroba font (opt-in L2, run in CI). The props are prepared
by the same browser prepass the delivery render uses; the verifier renders the frame and a
glyph-hidden twin, and compares each row with a HarfBuzz-shaped reference.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib.persian_film_type import prepare_film_type_props
from lib.persian_glyph_verify import verify_project
from tests.l2.test_issue232_hook_hierarchy_and_caption_band import ROOT, _hook_props

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)


def _project(tmp_path: Path) -> tuple[Path, dict]:
    props = _hook_props()
    props["moments"].append({
        "id": "m-body", "kind": "statement", "startSeconds": 8.0, "endSeconds": 12.0,
        "segments": [{"role": "hero", "text": "پیام بعد از قرار اول"}],
    })
    prepared = prepare_film_type_props(props, ROOT / "remotion-composer", scratch_dir=tmp_path)
    project = tmp_path / "project"
    (project / "renders").mkdir(parents=True)
    path = project / "renders" / "candidate.mp4.props.json"
    path.write_text(json.dumps(prepared, ensure_ascii=False), encoding="utf-8")
    return project, prepared


def test_the_real_composition_passes_glyph_order(tmp_path: Path) -> None:
    project, _ = _project(tmp_path)
    report = verify_project(project)
    assert report["status"] == "pass", json.dumps(report, ensure_ascii=False, indent=1)


def test_a_reference_with_reversed_words_fails_against_the_real_pixels(tmp_path: Path) -> None:
    project, _ = _project(tmp_path)

    def reverse(moment_id: str, rows: list[dict]) -> list[dict]:
        for row in rows:
            if moment_id == "m-body" and len(row["text"].split()) > 1:
                row["text"] = " ".join(reversed(row["text"].split()))
        return rows

    report = verify_project(project, reference_rows=reverse)
    assert report["moments"]["m-body"]["status"] == "fail", json.dumps(report, ensure_ascii=False, indent=1)
