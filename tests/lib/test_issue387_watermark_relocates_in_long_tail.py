"""#387: the brand must keep relocating in a long text-free tail.

2026-10-04 v3 acceptance run (55.6s, Film Type 2.16): both upper anchors were clear
from 21.2s to the end, yet the coverage-aware planner parked the brand at upper-right
for 34s. Every 3-anchor schedule overshot the 75% coverage cap by ~1.2s, the 2-anchor
one by ~0.3s, and the cap was ranked above the long-form relocation target.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Exact boundaries and clearance of that run: lower anchors are closed by captions
# throughout, upper anchors only while moment-ev-04 holds the frame.
DRIVER = r'''
import { planCoverageAwareBrand } from "./src/persian/filmType/watermark24.ts";
const times=[5,7.08,7.55,8.02,10.06,10.26,10.46,11,12.663,12.912333333333335,16.873,16.873333333333335,17,17.805,21.22122222222222,21.222,21.22222222222222,23,25.161,25.162,28.039,28.04,29,32.36,32.61,35,36.661,37.77,38.02,39.14,39.68,41,44.099,44.1,47,47.46,47.63,47.8,50.397,50.799,53,55.577,55.606667];
const rects={"lower-left":{x:.1,y:.44,w:.24,h:.04},"upper-left":{x:.1,y:.15,w:.24,h:.04},"lower-right":{x:.58,y:.44,w:.24,h:.04},"upper-right":{x:.58,y:.15,w:.24,h:.04}};
const clear=(r,a,b)=>!(r.y>.3)&&!(a<17.805&&b>12.663)&&!(b>55.577+1e-9)&&!(a<21.222&&b>17.805&&a<17.805);
const cfg={minDwellSeconds:6,maxRelocations:5,targetDwellSeconds:12,minCoverageRatio:.55,targetCoverageRatio:.65,maxCoverageRatio:.75,longFormThresholdSeconds:30,minLongFormRelocations:2,minLongFormVerticalBands:2,verticalDiversityMinDwellSeconds:4};
const plan=planCoverageAwareBrand(55.606667,times,["lower-left","lower-right","upper-left","upper-right"],rects,clear,cfg,5);
process.stdout.write(JSON.stringify(plan.map(s=>[s.zone,s.startSeconds,s.endSeconds])));
'''


def _plan() -> list[list]:
    esbuild = ROOT / "remotion-composer" / "node_modules" / ".bin" / "esbuild"
    if shutil.which("node") is None or not esbuild.exists():
        pytest.skip("node/esbuild not available")
    composer = ROOT / "remotion-composer"
    driver = composer / ".issue387-wm-driver.mjs"
    bundle = composer / ".issue387-wm-bundle.mjs"
    driver.write_text(DRIVER, encoding="utf-8")
    try:
        subprocess.run([str(esbuild), str(driver), "--bundle", "--format=esm", "--platform=node",
                        f"--outfile={bundle}", "--log-level=error"], check=True, cwd=composer, timeout=120)
        return json.loads(subprocess.run(["node", str(bundle)], check=True, capture_output=True,
                                         text=True, cwd=composer, timeout=60).stdout)
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


def test_long_form_tail_meets_the_relocation_target() -> None:
    plan = _plan()
    moves = sum(1 for a, b in zip(plan, plan[1:]) if a[0] != b[0])
    assert moves >= 2, plan


def test_no_dwell_holds_most_of_the_film() -> None:
    plan = _plan()
    longest = max(end - start for _, start, end in plan)
    # The defect was one 34.4s dwell in a 55.6s film.
    assert longest < 20.0, plan
