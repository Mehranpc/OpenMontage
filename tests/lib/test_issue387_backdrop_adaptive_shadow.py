"""#387: the text shadow follows the footage brightness under the text (v3_staged).

2026-10-04 acceptance: the same field (dark, strong, peak 0.4) was clearly visible
over a bright wall and vanished over a dark sweater, so it read as "shadow in one
shot, none in the next".
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lib import persian_backdrop_luma as backdrop

ROOT = Path(__file__).resolve().parents[2]
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available")


def test_multiplier_is_monotonic_and_bounded():
    assert backdrop.luma_multiplier(0.0) == backdrop.MIN_MULTIPLIER
    assert backdrop.luma_multiplier(1.0) == backdrop.MAX_MULTIPLIER
    values = [backdrop.luma_multiplier(x / 20) for x in range(21)]
    assert values == sorted(values)
    assert backdrop.luma_multiplier(0.35) == pytest.approx(1.0, abs=1e-3)


def test_samples_stay_inside_the_overlap():
    assert backdrop.sample_times(2.0, 3.0) == [2.5]
    assert backdrop.sample_times(0.0, 6.0) == [0.3, 3.0, 5.7]
    assert backdrop.sample_times(4.0, 4.0) == []


def _split_clip(path: Path) -> Path:
    """Upper half bright (wall), lower half dark (sweater), 1080x1920, 3s."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xE6E6E6:s=1080x960:d=3",
         "-f", "lavfi", "-i", "color=c=0x141414:s=1080x960:d=3", "-filter_complex", "vstack",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=120,
    )
    return path


@needs_ffmpeg
def test_bright_backdrop_strengthens_and_dark_backdrop_lightens(tmp_path):
    clip = _split_clip(tmp_path / "split.mp4")
    upper = {"x": 0.2, "y": 0.1, "w": 0.6, "h": 0.1}
    lower = {"x": 0.2, "y": 0.75, "w": 0.6, "h": 0.1}
    props = {
        "format": "vertical",
        "shots": [{"id": "s1", "startSeconds": 0.0, "endSeconds": 3.0, "sourceInSeconds": 0.0}],
        "moments": [{"id": "bright", "startSeconds": 0.0, "endSeconds": 2.5},
                    {"id": "dark", "startSeconds": 0.5, "endSeconds": 1.0},
                    {"id": "unplaced", "startSeconds": 0.0, "endSeconds": 1.0}],
        "filmType": {"moments": {"bright": {"rect": upper}, "dark": {"rect": lower}}},
    }
    result = backdrop.measure_backdrop(props, {"s1": clip})
    assert result["version"] == backdrop.BACKDROP_POLICY_VERSION
    bright, dark = result["moments"]["bright"]["s1"], result["moments"]["dark"]["s1"]
    assert bright["luma"] > 0.8 and bright["multiplier"] == backdrop.MAX_MULTIPLIER and bright["samples"] == 3
    assert dark["luma"] < 0.12 and dark["multiplier"] == backdrop.MIN_MULTIPLIER and dark["samples"] == 1
    assert "unplaced" not in result["moments"]


@needs_ffmpeg
def test_unreadable_source_keeps_the_default_strength(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    props = {"shots": [{"id": "s1", "startSeconds": 0.0, "endSeconds": 2.0}],
             "moments": [{"id": "m", "startSeconds": 0.0, "endSeconds": 1.0}],
             "filmType": {"moments": {"m": {"rect": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.1}}}}}
    entry = backdrop.measure_backdrop(props, {"s1": broken})["moments"]["m"]["s1"]
    assert entry["multiplier"] == 1.0 and entry["error"]


def test_renderer_applies_the_measured_multiplier():
    components = (ROOT / "remotion-composer/src/persian/filmType/components.tsx").read_text(encoding="utf-8")
    video = (ROOT / "remotion-composer/src/persian/PersianFootageVideo.tsx").read_text(encoding="utf-8")
    assert "backdropMultiplier(backdrop, moment.id, activeShot?.id)" in components
    assert "backdrop={filmTypeBackdrop}" in video
    compose = (ROOT / "tools/video/persian_compose.py").read_text(encoding="utf-8")
    assert 'prepared["filmTypeBackdrop"] = measure_backdrop(prepared, shot_sources)' in compose


DRIVER = r'''
import { backdropMultiplier } from "./src/persian/filmType/backdrop.ts";
const b={version:"1.0",moments:{m:{s1:{multiplier:1.3},s2:{multiplier:0.7},s3:{multiplier:1,error:"x"}}}};
process.stdout.write(JSON.stringify([backdropMultiplier(b,"m","s1"),backdropMultiplier(b,"m","s2"),
  backdropMultiplier(b,"m","s3"),backdropMultiplier(b,"m",undefined),backdropMultiplier(undefined,"m","s1"),
  backdropMultiplier(b,"other","s1")]));
'''


def test_backdrop_multiplier_lookup_defaults_to_one():
    esbuild = ROOT / "remotion-composer" / "node_modules" / ".bin" / "esbuild"
    if shutil.which("node") is None or not esbuild.exists():
        pytest.skip("node/esbuild not available")
    composer = ROOT / "remotion-composer"
    driver, bundle = composer / ".issue387-backdrop-driver.mjs", composer / ".issue387-backdrop-bundle.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    try:
        subprocess.run([str(esbuild), str(driver), "--bundle", "--format=esm", "--platform=node",
                        f"--outfile={bundle}", "--log-level=error"],
                       check=True, cwd=composer, timeout=120)
        out = subprocess.run(["node", str(bundle)], check=True, capture_output=True, text=True,
                             cwd=composer, timeout=60).stdout
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)
    import json
    assert json.loads(out) == [1.3, 0.7, 1, 1, 1, 1]
