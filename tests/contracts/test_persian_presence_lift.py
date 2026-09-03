"""Presence-lift parity for short Persian heroes.

The eye judges ink mass, not em size. With the compressed ladder every moment
lands on rung 0 at the same 123px, so a micro hero (``قهوه`` — 241px in an
881px column) reads tiny beside a normal one (593px) at the identical size.
The old ladder hid this via spread (short → big rung); the compressed ladder
needs an explicit lift.

``presenceLiftFit`` (in ``layout.ts``) lifts a moment whose heroes are all
short single lines and whose stack is narrow, by walking the hero size up in
``PRESENCE_LIFT_STEP`` increments capped at ``computeShortHeroMaxPx``. Height
and width safety come from re-running ``tryHeroSize`` — the same machinery as
the ladder search.

These tests bundle ``tokens.ts`` + ``layout.ts`` with esbuild and run them in
Node with the real Estedad fonts via node-canvas — the same driver pattern as
``tools/video/persian_compose.py::_maybe_attach_stack_heights``. Parsing
TypeScript with a regex would give a second thing to keep in sync.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_DIR = REPO_ROOT / "remotion-composer"


@pytest.fixture(scope="module")
def lifted() -> dict:
    """Fit four canonical moments and return their fitted results + tokens."""
    if shutil.which("node") is None:
        pytest.skip("node not available")

    esbuild = COMPOSER_DIR / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        pytest.skip("esbuild not installed; run npm install in remotion-composer")
    if not (COMPOSER_DIR / "node_modules" / "canvas" / "package.json").exists():
        pytest.skip("node-canvas not installed")

    driver = COMPOSER_DIR / ".persian-lift-driver.mjs"
    bundle = COMPOSER_DIR / ".persian-lift-bundle.mjs"

    driver.write_text(
        """
import { createCanvas, registerFont } from 'canvas';
registerFont('./public/fonts/estedad/Estedad-Medium.ttf', { family: 'Estedad', weight: '500' });
registerFont('./public/fonts/estedad/Estedad-Bold.ttf', { family: 'Estedad', weight: '700' });
registerFont('./public/fonts/estedad/Estedad-Black.ttf', { family: 'Estedad', weight: '900' });
globalThis.document = { createElement: (tag) => { if(tag!=='canvas') throw new Error(tag); return createCanvas(3000,1000); } };
globalThis.FontFace = class { constructor(f,s,d){this.family=f;this.src=s;this.desc=d;} load(){return Promise.resolve(this);} };
globalThis.document.fonts = { add:()=>{}, load:()=>Promise.resolve([]), check:()=>true };
const { estedadReady } = await import('./src/persian/fonts');
await estedadReady;
const { fitMoment } = await import('./src/persian/layout');
import {
  HERO_LADDER_PX, SHORT_HERO_MAX_CHARS, SHORT_HERO_FILL_FRACTION,
  SHORT_HERO_MAX_RATIO, PRESENCE_LIFT_STEP,
  computeLineBudgetPx, computeMaxStackPx, computeShortHeroMaxPx,
} from './src/persian/tokens.ts';

const fmt = 'vertical';
const moments = {
  // Micro hero: two short words, narrow stack — runs to the cap.
  micro: [
    { role: 'lead', text: 'شروع روزت با' },
    { role: 'hero', text: 'قهوه' },
  ],
  // Mid hero: short single-line hero but a wide lead — one step, then fill stops it.
  mid: [
    { role: 'lead', text: 'مطالعهٔ دانشگاه اولوی فنلاند روی' },
    { role: 'hero', text: '۲۲۶۴ نفر' },
  ],
  // Normal hero: long multi-word hero — must stay on its ladder rung.
  normal: [
    { role: 'lead', text: 'با وزن مشابه' },
    { role: 'hero', text: 'چربی کمتر، عضلهٔ بیشتر' },
  ],
  // Long hero past the char ceiling — must stay even though narrow.
  longHero: [
    { role: 'lead', text: 'نگاه کن' },
    { role: 'hero', text: 'چربی کمتر، عضلهٔ بیشتر و قند کمتر' },
  ],
  // Tall stack: six short blocks — narrow enough to qualify, tall enough
  // that height breaks the lift before the cap.
  tall: [
    { role: 'lead', text: 'نگاه کن' },
    { role: 'hero', text: 'قهوه' },
    { role: 'lead', text: 'ببین', revealAfterSeconds: 2.0 },
    { role: 'hero', text: 'چای', revealAfterSeconds: 2.0 },
    { role: 'tail', text: 'بخور و بچش', revealAfterSeconds: 4.0 },
    { role: 'source', text: 'منبع' },
  ],
};

const out = { tokens: {
  ladderTop: HERO_LADDER_PX[fmt][0],
  shortMaxChars: SHORT_HERO_MAX_CHARS,
  fillFraction: SHORT_HERO_FILL_FRACTION,
  maxRatio: SHORT_HERO_MAX_RATIO,
  liftStep: PRESENCE_LIFT_STEP,
  cap: computeShortHeroMaxPx(fmt),
  budget: computeLineBudgetPx(fmt),
  heightBudget: computeMaxStackPx(fmt),
}, moments: {} };
for (const [name, segs] of Object.entries(moments)) {
  const f = fitMoment(segs, fmt, 'statement');
  out.moments[name] = {
    heroPx: f.heroPx,
    leadPx: f.leadPx,
    ladderIndex: f.ladderIndex,
    presenceLiftPx: f.presenceLiftPx ?? null,
    heightPx: f.heightPx,
    widthPx: f.widthPx,
    escalation: f.segments.map(s => s.escalation),
    heroLines: f.segments.filter(s => s.role === 'hero').map(s => s.lines.length),
  };
}
process.stdout.write(JSON.stringify(out));
""",
        encoding="utf-8",
    )

    try:
        build = subprocess.run(
            [
                str(esbuild),
                str(driver),
                "--bundle",
                "--format=esm",
                "--platform=node",
                "--external:canvas",
                f"--outfile={bundle}",
                "--log-level=error",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=COMPOSER_DIR,
        )
        if build.returncode != 0:
            pytest.fail(f"esbuild failed: {build.stderr}")
        run = subprocess.run(
            ["node", str(bundle)],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=COMPOSER_DIR,
        )
        if run.returncode != 0:
            pytest.fail(f"node driver failed: {run.stderr}")
        return json.loads(run.stdout)
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


def test_micro_moment_runs_to_the_cap(lifted: dict) -> None:
    """A micro hero never reaches the fill — the cap dominates."""
    micro = lifted["moments"]["micro"]
    top = lifted["tokens"]["ladderTop"]
    assert micro["presenceLiftPx"] is not None, "FittedMoment lacks presenceLiftPx"
    assert micro["presenceLiftPx"] > 0
    assert micro["heroPx"] == lifted["tokens"]["cap"]
    assert micro["heroPx"] > top


def test_mid_moment_stops_on_fill(lifted: dict) -> None:
    """A mid-width stack lifts once, then carries its weight — continuity."""
    mid = lifted["moments"]["mid"]
    assert mid["presenceLiftPx"] > 0
    assert lifted["tokens"]["ladderTop"] < mid["heroPx"] < lifted["tokens"]["cap"]


def test_lifted_moments_stay_in_budget_without_escalation(lifted: dict) -> None:
    """The lift reuses the ladder machinery, so its safety is structural."""
    for name in ("micro", "mid"):
        moment = lifted["moments"][name]
        assert all(e == "none" for e in moment["escalation"]), name
        assert moment["heightPx"] <= lifted["tokens"]["heightBudget"], name


def test_normal_moment_stays_on_its_rung(lifted: dict) -> None:
    """A two-line hero is a phrase, not a word — no lift."""
    normal = lifted["moments"]["normal"]
    assert normal["presenceLiftPx"] == 0
    assert normal["heroPx"] == lifted["tokens"]["ladderTop"]
    assert normal["ladderIndex"] == 0


def test_long_hero_never_lifts(lifted: dict) -> None:
    """Past the char ceiling the hero is a phrase, not a word — no lift."""
    long = lifted["moments"]["longHero"]
    assert long["presenceLiftPx"] == 0
    # A long hero drops down the ladder to fit; the lift must not add back on top.
    assert long["heroPx"] <= lifted["tokens"]["ladderTop"]


def test_cap_is_respected(lifted: dict) -> None:
    """Pure fit-to-width would set قهوه near 360px; the cap dominates micro cases."""
    cap = lifted["tokens"]["cap"]
    top = lifted["tokens"]["ladderTop"]
    assert cap > top
    for name, moment in lifted["moments"].items():
        assert moment["heroPx"] <= cap, f"{name} escaped the cap"


def test_height_break_stops_the_lift(lifted: dict) -> None:
    """A tall stack must stop lifting before it overflows, not after."""
    tall = lifted["moments"]["tall"]
    assert tall["heightPx"] <= lifted["tokens"]["heightBudget"]
    assert tall["heroPx"] <= lifted["tokens"]["cap"]
    # The tall stack lifts less than the micro one (or not at all) — height broke it.
    assert tall["heroPx"] <= lifted["moments"]["micro"]["heroPx"]


class TestPresenceTokenRelations:
    """The lift tokens relate to each other and to the ladder by construction."""

    def test_char_ceiling_is_a_word_not_a_phrase(self, lifted: dict) -> None:
        assert 0 < lifted["tokens"]["shortMaxChars"] <= 30

    def test_fill_fraction_is_a_fraction(self, lifted: dict) -> None:
        assert 0 < lifted["tokens"]["fillFraction"] < 1

    def test_lift_step_is_gradual(self, lifted: dict) -> None:
        assert 1 < lifted["tokens"]["liftStep"] < 1.5

    def test_cap_derives_from_the_ladder_top(self, lifted: dict) -> None:
        expected = round(
            lifted["tokens"]["ladderTop"] * lifted["tokens"]["maxRatio"]
        )
        assert lifted["tokens"]["cap"] == expected
