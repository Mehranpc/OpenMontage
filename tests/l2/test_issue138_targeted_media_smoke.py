"""Issue #138 L2 smoke: exercise real Chromium and FFmpeg on a tiny slice.

This suite is intentionally opt-in because it requires the CI media toolchain.
It must not download media or render a complete production.  The JSON evidence
file is uploaded by the dedicated CI job so a failure can be diagnosed without
starting another P4 shadow run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from lib.persian_design import resolve_design
from lib.persian_film_type import prepare_film_type_props


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = Path(
    os.environ.get(
        "OPENMONTAGE_L2_EVIDENCE_PATH",
        ROOT / "test-artifacts" / "issue138-l2" / "evidence.json",
    )
)

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") != "1",
    reason="opt-in real Chromium/FFmpeg suite",
)


def _write_evidence(payload: dict) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _targeted_props(source: Path) -> dict:
    return {
        "format": "vertical",
        "durationSeconds": 1.0,
        "design": resolve_design(
            {"version": 2, "profile": "film-type", "seed": "issue138-l2"}
        ),
        "watermark": {"persianText": "", "latinText": ""},
        "typographicBeats": [],
        "captionMode": "sidecar_only",
        "captions": [],
        "shots": [
            {
                "id": "shot-l2",
                "source": str(source),
                "startSeconds": 0.0,
                "endSeconds": 1.0,
                "avoidRegions": [
                    {
                        "x": 0.0,
                        "y": 0.14,
                        "w": 0.22,
                        "h": 0.22,
                        "priority": "hard",
                        "startSeconds": 0.0,
                        "endSeconds": 1.0,
                    }
                ],
            }
        ],
        "moments": [
            {
                "id": "moment-l2",
                "kind": "statement",
                "startSeconds": 0.0,
                "endSeconds": 1.0,
                "presentation": {"placement": "auto"},
                "segments": [{"role": "hero", "text": "نیاز به توجه"}],
            }
        ],
    }


def test_real_browser_and_ffmpeg_targeted_slice(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    assert ffmpeg, "L2 requires a real ffmpeg executable"
    assert ffprobe, "L2 requires a real ffprobe executable"

    source = tmp_path / "one-second-source.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x20242b:s=1080x1920:r=25:d=1",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    duration = float(
        subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
    )

    prepared = prepare_film_type_props(
        _targeted_props(source), ROOT / "remotion-composer", scratch_dir=tmp_path
    )
    layout = prepared["filmType"]["moments"]["moment-l2"]
    hard_region = prepared["shots"][0]["avoidRegions"][0]
    rect = layout["rect"]
    overlaps = not (
        rect["x"] + rect["w"] <= hard_region["x"]
        or hard_region["x"] + hard_region["w"] <= rect["x"]
        or rect["y"] + rect["h"] <= hard_region["y"]
        or hard_region["y"] + hard_region["h"] <= rect["y"]
    )

    evidence = {
        "layer": "L2",
        "trackingIssue": 138,
        "fixture": "one-second-generated-source",
        "ffmpeg": {"sourceBytes": source.stat().st_size, "durationSeconds": duration},
        "browser": {
            "inputHash": prepared["filmType"]["inputHash"],
            "layoutVersion": prepared["filmType"]["version"],
            "momentId": "moment-l2",
            "placement": layout["placement"],
            "subjectSafety": layout["subjectSafety"],
            "hardRegionOverlap": overlaps,
        },
    }
    _write_evidence(evidence)

    assert source.stat().st_size > 0
    assert duration == pytest.approx(1.0, abs=0.08)
    assert prepared["watermarkPlanMeasured"] is True
    assert layout["subjectSafety"] == "checked-against-supplied-regions"
    assert overlaps is False
