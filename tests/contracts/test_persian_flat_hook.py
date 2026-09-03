"""Claim+qualifier hook (the approved style) and the flat-hook display treatment.

Moment 1 of the coffee video is a `kind: "hook"` moment in the claim+qualifier
style: a `hero` carrying the claim in accent plus a `tail` completing it in
primary ink — no `accentWords`, the colour comes from the roles. It fits at rung
93 with a 68px Black qualifier, one line each, inside the silhouette band.

The flat display style — a single `hero` carrying `accentWords`, the whole
moment at one size with the emphasis in colour — is kept working for a
single-clause sentence where any split is arbitrary. It fits one rung below the
top in three lines at weight 700. Both styles flow through the declared `kind`
plus one structural predicate each (`isClaimQualifierHook` /
`isFlatDisplayBlock` in `layout.ts`), so the size, weight, leading and line-cap
decisions cannot drift apart.

These tests bundle `tokens.ts` + `layout.ts` with esbuild and run them in Node
with the real Estedad fonts via node-canvas. Hook strings are read
programmatically out of `projects/coffee-hormones-fa/artifacts/edit_decisions.json`
— the ZWNJ (U+200C) in the text must survive verbatim.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_DIR = REPO_ROOT / "remotion-composer"
EDIT_DECISIONS = (
    REPO_ROOT / "projects" / "coffee-hormones-fa" / "artifacts" / "edit_decisions.json"
)


@pytest.fixture(scope="module")
def hook() -> dict:
    """Fit the real opening hook (claim+qualifier), the flat style, and guards."""
    if shutil.which("node") is None:
        pytest.skip("node not available")

    esbuild = COMPOSER_DIR / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        pytest.skip("esbuild not installed; run npm install in remotion-composer")
    if not (COMPOSER_DIR / "node_modules" / "canvas" / "package.json").exists():
        pytest.skip("node-canvas not installed")

    edit = json.loads(EDIT_DECISIONS.read_text(encoding="utf-8"))
    moments = edit["persian"]["moments"]
    assert moments[0]["kind"] == "hook", moments[0]["kind"]
    # Moment 3: an ordinary two-line hero, for the leading comparison.
    ordinary = moments[2]["segments"]

    driver = COMPOSER_DIR / ".tmp" / "hook_driver.mjs"
    bundle = COMPOSER_DIR / ".tmp" / "hook_driver.bundle.mjs"

    driver.write_text(
        """
import { createCanvas, registerFont } from 'canvas';
registerFont('./public/fonts/estedad/Estedad-Medium.ttf', { family: 'Estedad', weight: '500' });
registerFont('./public/fonts/estedad/Estedad-Bold.ttf', { family: 'Estedad', weight: '700' });
registerFont('./public/fonts/estedad/Estedad-Black.ttf', { family: 'Estedad', weight: '900' });
globalThis.document = { createElement: (tag) => { if(tag!=='canvas') throw new Error(tag); return createCanvas(3000,1000); } };
globalThis.FontFace = class { constructor(f,s,d){this.family=f;this.src=s;this.desc=d;} load(){return Promise.resolve(this);} };
globalThis.document.fonts = { add:()=>{}, load:()=>Promise.resolve([]), check:()=>true };
const { estedadReady } = await import('../src/persian/fonts');
await estedadReady;
const { fitMoment, silhouetteRatio, isFlatDisplayBlock, isClaimQualifierHook,
  tailPxForMoment, stackGapPxForMoment, weightForRole, ROLE_WEIGHT,
  FLAT_DISPLAY_HERO_WEIGHT } = await import('../src/persian/layout');
import {
  HERO_LADDER_PX, HERO_MAX_LINES, FLAT_HERO_MAX_LINES,
  FLAT_HERO_LADDER_OFFSET, HOOK_HERO_LADDER_OFFSET, HOOK_TAIL_RATIO,
  HOOK_TAIL_WEIGHT, HOOK_SILHOUETTE_MIN_RATIO, HOOK_SILHOUETTE_MAX_RATIO,
  BLOCK_LEADING_RATIO, DISPLAY_LEADING_RATIO, STACK_GAP_RATIO,
  computeLineBudgetPx, computeMaxStackPx,
  computeLeadPx, computeStackGapPx,
} from '../src/persian/tokens.ts';
import { TYPOGRAPHY } from '../src/persian/tokens.ts';
import { HOOK_SEGMENT_STAGGER_FRAMES } from '../src/persian/tokens.ts';
import fs from 'fs';

const fmt = 'vertical';
const ed = JSON.parse(fs.readFileSync(
  '../projects/coffee-hormones-fa/artifacts/edit_decisions.json', 'utf-8'));
const hookMoment = ed.persian.moments[0];
const hookSegs = hookMoment.segments;
const ordinarySegs = ed.persian.moments[2].segments;
// Flat style: the previously rejected one-size sentence, declared a hook.
const flatSegs = [{ role: 'hero',
  text: 'می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟',
  accentWords: ['قهوه', 'هورمون‌هات'] }];
// Scope guard: the identical flat text with accentWords removed, undeclared.
const strippedSegs = [{ role: 'hero',
  text: 'می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟' }];
// Hook lift guard: a micro hero declared a hook must not lift.
const microHookSegs = [{ role: 'hero', text: 'قهوه' },
  { role: 'tail', text: 'بخور و بچش' }];

const r2 = (x) => Math.round(x * 100) / 100;
function fitted(segs, kind) {
  const f = fitMoment(segs, fmt, kind);
  return {
    heroPx: f.heroPx,
    leadPx: f.leadPx,
    ladderIndex: f.ladderIndex,
    presenceLiftPx: f.presenceLiftPx ?? null,
    heightPx: r2(f.heightPx),
    widthPx: r2(f.widthPx),
    stackGapPx: f.stackGapPx,
    ratio: kind === 'hook' ? r2(silhouetteRatio(f)) : null,
    segs: f.segments.map((s) => ({
      role: s.role,
      fontSizePx: s.fontSizePx,
      weight: s.weight,
      lineGapPx: s.lineGapPx,
      escalation: s.escalation,
      lines: s.lines.map((l) => l.join(' ')),
      painted: s.paintedWidthPerLine.map(r2),
    })),
  };
}

const hook = fitted(hookSegs, hookMoment.kind);
const flat = fitted(flatSegs, 'hook');
const stripped = fitted(strippedSegs, 'statement');
const microHook = fitted(microHookSegs, 'hook');
const ordinary = fitted(ordinarySegs, 'statement');
// Per-line painted widths for the hook, for the silhouette check.
const { measureWords } = await import('../src/persian/measure');
const gapRatio = TYPOGRAPHY[fmt].wordGapRatio;
// Hard constraint: every moment after the first, fitted for the baseline diff.
const others = ed.persian.moments.slice(1).map((m) => ({
  id: m.id,
  kind: m.kind,
  ...fitted(m.segments, m.kind),
}));

const out = { tokens: {
  ladderTop: HERO_LADDER_PX[fmt][0],
  ladder: HERO_LADDER_PX[fmt],
  hookOffset: HOOK_HERO_LADDER_OFFSET,
  flatOffset: FLAT_HERO_LADDER_OFFSET,
  tailRatio: HOOK_TAIL_RATIO,
  tailWeight: HOOK_TAIL_WEIGHT,
  silMin: HOOK_SILHOUETTE_MIN_RATIO,
  silMax: HOOK_SILHOUETTE_MAX_RATIO,
  hookStagger: HOOK_SEGMENT_STAGGER_FRAMES,
  heroMaxLines: HERO_MAX_LINES,
  flatMaxLines: FLAT_HERO_MAX_LINES,
  blockLeading: BLOCK_LEADING_RATIO,
  displayLeading: DISPLAY_LEADING_RATIO,
  stackGapRatio: STACK_GAP_RATIO,
  budget: r2(computeLineBudgetPx(fmt)),
  heightBudget: r2(computeMaxStackPx(fmt)),
  roleHeroWeight: ROLE_WEIGHT.hero,
  roleTailWeight: ROLE_WEIGHT.tail,
  flatWeight: FLAT_DISPLAY_HERO_WEIGHT,
  leadAtTop: computeLeadPx(HERO_LADDER_PX[fmt][0], fmt),
  gapAtTop: computeStackGapPx(computeLeadPx(HERO_LADDER_PX[fmt][0], fmt)),
  tailAtHookRung: tailPxForMoment(HERO_LADDER_PX[fmt][HOOK_HERO_LADDER_OFFSET],
    computeLeadPx(HERO_LADDER_PX[fmt][HOOK_HERO_LADDER_OFFSET], fmt), true),
  gapAtHookRung: stackGapPxForMoment(
    computeLeadPx(HERO_LADDER_PX[fmt][HOOK_HERO_LADDER_OFFSET], fmt),
    tailPxForMoment(HERO_LADDER_PX[fmt][HOOK_HERO_LADDER_OFFSET],
      computeLeadPx(HERO_LADDER_PX[fmt][HOOK_HERO_LADDER_OFFSET], fmt), true),
    true),
  hookTailWeight: weightForRole('tail', hookSegs, true),
  ordinaryTailWeight: weightForRole('tail', ordinarySegs, false),
}, hook, flat, stripped, microHook, ordinary, others,
  predicate: {
    hookIsClaimQualifier: isClaimQualifierHook(hookSegs),
    hookIsFlat: isFlatDisplayBlock(hookSegs),
    flatIsClaimQualifier: isClaimQualifierHook(flatSegs),
    flatIsFlat: isFlatDisplayBlock(flatSegs),
    strippedIsFlat: isFlatDisplayBlock(strippedSegs),
    ordinaryIsFlat: isFlatDisplayBlock(ordinarySegs),
    ordinaryIsClaimQualifier: isClaimQualifierHook(ordinarySegs),
    heroNoAccentsIsFlat: isFlatDisplayBlock([{ role: 'hero', text: 'قهوه' }]),
    flatWithSourceIsFlat: isFlatDisplayBlock([
      { role: 'hero', text: 'قهوه', accentWords: ['قهوه'] },
      { role: 'source', text: 'منبع' },
    ]),
    flatWithLeadSiblingIsFlat: isFlatDisplayBlock([
      { role: 'lead', text: 'نگاه کن' },
      { role: 'hero', text: 'قهوه', accentWords: ['قهوه'] },
    ]),
  } };
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
        payload = json.loads(run.stdout)
        return payload
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)


class TestClaimQualifierHook:
    """The approved style pins: rung 93, 68px Black qualifier, step silhouette."""

    def test_hook_fits_two_rungs_below_the_top(self, hook: dict) -> None:
        fitted = hook["hook"]
        tokens = hook["tokens"]
        assert tokens["ladderTop"] == 123
        assert tokens["hookOffset"] == 2
        assert fitted["heroPx"] == tokens["ladder"][tokens["hookOffset"]] == 93
        assert fitted["ladderIndex"] == tokens["hookOffset"]
        assert fitted["presenceLiftPx"] == 0

    def test_tail_derives_from_tokens_not_a_literal(self, hook: dict) -> None:
        fitted = hook["hook"]
        tokens = hook["tokens"]
        assert tokens["tailRatio"] == 0.73
        assert tokens["tailAtHookRung"] == 68
        tail = next(s for s in fitted["segs"] if s["role"] == "tail")
        assert tail["fontSizePx"] == tokens["tailAtHookRung"]
        assert tail["fontSizePx"] / fitted["heroPx"] == pytest.approx(
            tokens["tailRatio"], abs=0.01
        )

    def test_both_lines_share_the_weight_class(self, hook: dict) -> None:
        fitted = hook["hook"]
        tokens = hook["tokens"]
        assert tokens["tailWeight"] == 900
        assert tokens["hookTailWeight"] == 900
        for seg in fitted["segs"]:
            assert seg["weight"] == 900
        hero = next(s for s in fitted["segs"] if s["role"] == "hero")
        assert hero["weight"] == tokens["roleHeroWeight"]

    def test_each_segment_is_one_line(self, hook: dict) -> None:
        fitted = hook["hook"]
        assert [s["role"] for s in fitted["segs"]] == ["hero", "tail"]
        for seg in fitted["segs"]:
            assert len(seg["lines"]) == 1, (seg["role"], seg["lines"])
            assert seg["escalation"] == "none"

    def test_silhouette_reads_a_step_inside_the_band(self, hook: dict) -> None:
        fitted = hook["hook"]
        tokens = hook["tokens"]
        assert fitted["ratio"] == pytest.approx(0.647, abs=0.02)
        assert tokens["silMin"] <= fitted["ratio"] <= tokens["silMax"]

    def test_stack_geometry_matches_the_approved_frame(self, hook: dict) -> None:
        fitted = hook["hook"]
        tokens = hook["tokens"]
        assert tokens["gapAtHookRung"] == 37
        assert fitted["stackGapPx"] == tokens["gapAtHookRung"]
        assert fitted["heightPx"] == pytest.approx(251.68, abs=1.0)
        assert fitted["heightPx"] <= tokens["heightBudget"]

    def test_predicate_derives_claim_qualifier_from_structure(
        self, hook: dict
    ) -> None:
        predicate = hook["predicate"]
        assert predicate["hookIsClaimQualifier"] is True
        assert predicate["hookIsFlat"] is False
        assert predicate["flatIsClaimQualifier"] is False
        assert predicate["flatIsFlat"] is True
        assert predicate["ordinaryIsClaimQualifier"] is False
        assert predicate["ordinaryIsFlat"] is False

    def test_hook_tail_differs_from_an_ordinary_tail(self, hook: dict) -> None:
        """A future edit cannot silently make every moment's tail large and Black."""
        tokens = hook["tokens"]
        assert tokens["hookTailWeight"] == 900
        assert tokens["ordinaryTailWeight"] == 500
        assert tokens["tailRatio"] > 0.55

    def test_hook_never_lifts(self, hook: dict) -> None:
        """A micro hero declared a hook keeps its offset rung, not the cap."""
        micro = hook["microHook"]
        assert micro["presenceLiftPx"] == 0
        assert micro["heroPx"] == hook["tokens"]["ladder"][2] == 93

    def test_two_beat_stagger_is_nine_frames(self, hook: dict) -> None:
        assert hook["tokens"]["hookStagger"] == 9


class TestFlatHookDisplay:
    """The flat style is kept working: three lines one rung below, no lift."""

    def test_flat_fits_one_rung_below_the_top_in_three_lines_without_lift(
        self, hook: dict
    ) -> None:
        flat = hook["flat"]
        tokens = hook["tokens"]
        assert tokens["flatOffset"] == 1
        assert flat["heroPx"] == tokens["ladder"][tokens["flatOffset"]] == 110
        assert flat["ladderIndex"] == tokens["flatOffset"]
        assert len(flat["segs"]) == 1
        assert len(flat["segs"][0]["lines"]) == 3
        assert flat["presenceLiftPx"] == 0

    def test_flat_lines_are_the_balanced_split_with_tight_spread(
        self, hook: dict
    ) -> None:
        lines = hook["flat"]["segs"][0]["lines"]
        assert [len(line.split(" ")) for line in lines] == [2, 2, 2]
        assert lines == ["می‌دونی قهوه", "با هورمون‌هات", "چی‌کار می‌کنه؟"]

    def test_undeclared_flat_text_fits_as_an_ordinary_span(
        self, hook: dict
    ) -> None:
        """Structure proposes, the declaration disposes: without kind hook the
        identical text is an ordinary hero at the ladder top walk, not a display
        block."""
        stripped = hook["stripped"]
        assert stripped["heroPx"] == 69
        assert len(stripped["segs"][0]["lines"]) == 2

    def test_leading_is_display_for_flat_and_block_for_ordinary(
        self, hook: dict
    ) -> None:
        flat_seg = hook["flat"]["segs"][0]
        assert flat_seg["lineGapPx"] == round(
            flat_seg["fontSizePx"] * hook["tokens"]["displayLeading"]
        )
        assert flat_seg["lineGapPx"] == round(
            110 * hook["tokens"]["displayLeading"]
        ) == 42
        ordinary_hero = next(
            s for s in hook["ordinary"]["segs"] if s["role"] == "hero"
        )
        assert ordinary_hero["lineGapPx"] == round(
            ordinary_hero["fontSizePx"] * hook["tokens"]["blockLeading"]
        )
        assert len(ordinary_hero["lines"]) == 2

    def test_flat_hook_never_exceeds_flat_max_lines(self, hook: dict) -> None:
        for seg in hook["flat"]["segs"]:
            assert len(seg["lines"]) <= hook["tokens"]["flatMaxLines"]

    def test_predicate_guards_its_scope(self, hook: dict) -> None:
        predicate = hook["predicate"]
        assert predicate["flatIsFlat"] is True
        assert predicate["strippedIsFlat"] is False
        assert predicate["ordinaryIsFlat"] is False
        assert predicate["heroNoAccentsIsFlat"] is False
        assert predicate["flatWithSourceIsFlat"] is True
        assert predicate["flatWithLeadSiblingIsFlat"] is False

    def test_flat_clears_the_height_budget(self, hook: dict) -> None:
        assert hook["flat"]["heightPx"] <= hook["tokens"]["heightBudget"]
        assert hook["flat"]["heightPx"] == pytest.approx(449.78, abs=1.0)

    def test_flat_hero_weight_is_scoped_to_the_flat_block(
        self, hook: dict
    ) -> None:
        """The flat hero fits Bold while an ordinary hero fits Black.

        A future edit that makes the whole video Bold again must fail here,
        not silently leak. Derived from the tokens, never literals.
        """
        tokens = hook["tokens"]
        assert tokens["flatWeight"] == 700
        assert tokens["roleHeroWeight"] == 900
        assert hook["flat"]["segs"][0]["weight"] == tokens["flatWeight"]
        for seg in hook["stripped"]["segs"]:
            assert seg["weight"] == tokens["roleHeroWeight"]
        ordinary_hero = next(
            s for s in hook["ordinary"]["segs"] if s["role"] == "hero"
        )
        assert ordinary_hero["weight"] == tokens["roleHeroWeight"]

    def test_flat_style_fails_the_silhouette_band(self, hook: dict) -> None:
        """The gate finding, pinned: a balanced flat block ratios ~0.87–0.88,
        outside the band. Not a calibration problem — the flat style needs a
        hook-specific break objective before it can pass."""
        flat = hook["flat"]
        tokens = hook["tokens"]
        assert flat["ratio"] is not None
        assert flat["ratio"] > tokens["silMax"]


class TestHookScopeGuard:
    """The hard constraint: moments 2-8 fit exactly as the pinned baseline.

    The hook change applies to moment 1 and to nothing else. This pins every
    other moment's fitted geometry — hero size, lift, per-segment line counts,
    intra-block leading, stack height, hero weight — so any leak fails loudly.
    Baseline (vertical): m2 138/+15 stack 260.33 · m3 123/0 two-line hero
    398.73 · m4 172/+49 302.30 · m5 138/+15 257.47 · m6 138/+15 332.95 ·
    m7 123/0 243.92 · m8 155/+32 265.64, all heroes 900.
    """

    # (moment index, heroPx, presenceLiftPx, per-segment line counts, stack height).
    BASELINE = [
        (2, 138, 15, [1, 1], 260.33),
        (3, 123, 0, [1, 2], 398.73),
        (4, 172, 49, [1, 1], 302.30),
        (5, 138, 15, [1, 1], 257.47),
        (6, 138, 15, [1, 1, 1], 332.95),
        (7, 123, 0, [1, 1], 243.92),
        (8, 155, 32, [1, 1], 265.64),
    ]

    def test_other_moments_match_pinned_baseline(self, hook: dict) -> None:
        others = hook["others"]
        assert len(others) == 7
        for index, hero_px, lift_px, line_counts, stack_px in self.BASELINE:
            fitted = others[index - 2]
            assert fitted["id"] == f"moment-{index}", fitted["id"]
            assert fitted["heroPx"] == hero_px, (index, fitted["heroPx"])
            assert fitted["presenceLiftPx"] == lift_px, (
                index,
                fitted["presenceLiftPx"],
            )
            assert [len(s["lines"]) for s in fitted["segs"]] == line_counts, (
                index,
                [s["lines"] for s in fitted["segs"]],
            )
            for seg in fitted["segs"]:
                expected_gap = round(
                    seg["fontSizePx"] * hook["tokens"]["blockLeading"]
                )
                assert seg["lineGapPx"] == expected_gap, (
                    index,
                    seg["role"],
                    seg["lineGapPx"],
                    expected_gap,
                )
            assert fitted["heightPx"] == pytest.approx(stack_px, abs=1.0), (
                index,
                fitted["heightPx"],
            )
            for seg in fitted["segs"]:
                if seg["role"] == "hero":
                    assert seg["weight"] == 900, (index, seg["weight"])
                assert seg["escalation"] == "none", (index, seg["role"])


class TestHookSilhouetteBandParity:
    """The Python gate reads the same band the tokens declare."""

    def test_lib_band_matches_tokens_band(self, hook: dict) -> None:
        from lib.persian_moments import (
            HOOK_SILHOUETTE_MAX_RATIO,
            HOOK_SILHOUETTE_MIN_RATIO,
        )

        assert HOOK_SILHOUETTE_MIN_RATIO == hook["tokens"]["silMin"]
        assert HOOK_SILHOUETTE_MAX_RATIO == hook["tokens"]["silMax"]
