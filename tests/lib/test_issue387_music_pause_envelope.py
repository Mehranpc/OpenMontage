"""#387: a narration pause must not swell the music bed back to its intro level.

2026-10-04 v3 acceptance run: speech 0-7.08s and 8.02-55.38s. In the 0.94s pause the
bed rose from 0.148 to 0.72 (+13.7 dB) within 0.28s and fell back when the voice
resumed. The envelope is now a pure module, driven here through node+esbuild.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DUCK, BASE = 0.147911, 0.72

DRIVER = r'''
import { musicLevelAt } from "./src/persian/musicEnvelope.ts";
const intervals=[{startSeconds:1.0,endSeconds:7.08},{startSeconds:8.02,endSeconds:55.38}];
const levels={base:%(base)s,duck:%(duck)s};
const out=[];for(let f=0;f<=57*30;f++)out.push(musicLevelAt(f/30,intervals,levels));
process.stdout.write(JSON.stringify(out));
''' % {"base": BASE, "duck": DUCK}


@pytest.fixture(scope="module")
def levels() -> list[float]:
    esbuild = ROOT / "remotion-composer" / "node_modules" / ".bin" / "esbuild"
    if shutil.which("node") is None or not esbuild.exists():
        pytest.skip("node/esbuild not available")
    composer = ROOT / "remotion-composer"
    driver = composer / ".issue387-music-driver.mjs"
    bundle = composer / ".issue387-music-bundle.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    try:
        subprocess.run([str(esbuild), str(driver), "--bundle", "--format=esm", "--platform=node",
                        f"--outfile={bundle}", "--log-level=error"], check=True, cwd=composer, timeout=120)
        return json.loads(subprocess.run(["node", str(bundle)], check=True, capture_output=True,
                                         text=True, cwd=composer, timeout=60).stdout)
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


def _db(a: float, b: float) -> float:
    return 20 * math.log10(b / a)


def test_pause_inside_narration_lifts_at_most_6db(levels) -> None:
    pause = levels[int(7.08 * 30):int(8.02 * 30) + 1]
    assert _db(DUCK, max(pause)) <= 6.0 + 1e-6


def test_no_audible_step_inside_narration(levels) -> None:
    span = levels[int(1.0 * 30):int(55.38 * 30) + 1]
    worst = max(abs(_db(a, b)) for a, b in zip(span, span[1:]))
    assert worst < 1.0, worst


def test_intro_and_outro_keep_the_full_bed(levels) -> None:
    assert levels[0] == pytest.approx(BASE)
    assert levels[-1] == pytest.approx(BASE)
    assert levels[int(3.0 * 30)] == pytest.approx(DUCK)


def test_outro_release_is_gradual(levels) -> None:
    tail = levels[int(55.38 * 30):]
    assert max(abs(_db(a, b)) for a, b in zip(tail, tail[1:])) < 1.0
