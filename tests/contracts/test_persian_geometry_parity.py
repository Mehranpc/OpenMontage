"""Python ↔ TypeScript parity for the Persian layout geometry.

`lib/persian_verify.py` measures rendered frames against the geometry it believes the
renderer used. That belief is a transcription of `tokens.ts` — a second copy of numbers
whose first copy is in TypeScript. A transcription that drifts makes the verifier worse
than useless: it computes a moment zone that is not where the type is, finds no ink, and
reports either a false failure or, if the zone still catches part of the block, a false
pass on partial text.

Nothing else catches this. The verifier's own tests build synthetic frames from its own
constants, so they stay green when both the constants and the frames are wrong together.
Only comparing against the TypeScript source can detect it, which is what these do.

The tokens are read by bundling `tokens.ts` with esbuild and executing it in Node —
the same approach `test_persian_text_parity.py` uses, and for the same reason: parsing
TypeScript with a regex would give a second thing to keep in sync.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.persian_verify import (
    FORMAT_DIMENSIONS,
    MIN_LINE_PX,
    MOMENT_COLUMNS_PX,
    MOMENT_ZONE_FRACTION,
    SCRIM_CEILING,
    SCRIM_GUARANTEED_CONTRAST,
    SCRIM_PLATEAU_MARGIN_PX,
    STACK_GAP_RATIO,
    WATERMARK_TOP_FRACTION,
    expected_stack_gap_px,
    moment_centre_fraction,
    moment_columns,
    moment_zone,
    relative_luminance,
    scrim_plateau,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSER_DIR = REPO_ROOT / "remotion-composer"

FORMATS = ("vertical", "landscape")


@pytest.fixture(scope="module")
def tokens() -> dict:
    """Evaluate `tokens.ts` in Node and return the values the verifier depends on."""
    if shutil.which("node") is None:
        pytest.skip("node not available")

    esbuild = COMPOSER_DIR / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        pytest.skip("esbuild not installed; run npm install in remotion-composer")

    driver = COMPOSER_DIR / ".persian-geometry-driver.mjs"
    bundle = COMPOSER_DIR / ".persian-geometry-bundle.mjs"

    driver.write_text(
        """
import {
  FORMAT_DIMENSIONS, TYPOGRAPHY, SCRIM, SAFE_AREA, PERSIAN_PALETTE,
  TEXT_WIDTH_FRACTION, MAX_LEAD_LINES, INK_HEIGHT_EM, MOMENT_RULE_HEIGHT_PX,
  SCRIM_PLATEAU_MARGIN_PX,
  HERO_LADDER_PX, MOMENT_READ_CPS, MOMENT_FIXATION_SECONDS, MOMENT_BLOCK_SECONDS,
  MOMENT_MIN_SECONDS, MOMENT_MAX_SECONDS, MOMENT_MIN_GAP_SECONDS,
  OPENING_MOMENT_MAX_START_SECONDS, LEAD_RATIO, STACK_GAP_RATIO,
  WATERMARK_RESTING_TOP_PCT, WATERMARK_QUIET_CLEARANCE_PCT,
  computeLineBudgetPx, computeMomentZone, computeMomentColumns,
  computeMomentCentreFraction, computeTallestMomentPx, computeWatermarkQuietTopPct,
  computeLeadPx, computeStackGapPx, computeMaxStackPx, computeScrimPlateau,
} from "./src/persian/tokens.ts";

const formats = ["vertical", "landscape"];
const out = {
  scrimPeakAlpha: SCRIM.peakAlpha,
  scrimFalloffFraction: SCRIM.falloffFraction,
  scrimPlateauMarginPx: SCRIM_PLATEAU_MARGIN_PX,
  textWidthFraction: TEXT_WIDTH_FRACTION,
  maxLabelLines: MAX_LEAD_LINES,
  inkHeightEm: INK_HEIGHT_EM,
  momentRuleHeightPx: MOMENT_RULE_HEIGHT_PX,
  watermarkQuietClearancePct: WATERMARK_QUIET_CLEARANCE_PCT,
  palette: PERSIAN_PALETTE,
  readCps: MOMENT_READ_CPS,
  fixationSeconds: MOMENT_FIXATION_SECONDS,
  blockSeconds: MOMENT_BLOCK_SECONDS,
  minSeconds: MOMENT_MIN_SECONDS,
  maxSeconds: MOMENT_MAX_SECONDS,
  minGapSeconds: MOMENT_MIN_GAP_SECONDS,
  openingMaxStartSeconds: OPENING_MOMENT_MAX_START_SECONDS,
  leadRatio: LEAD_RATIO,
  stackGapRatio: STACK_GAP_RATIO,
  formats: {},
};
for (const f of formats) {
  const t = TYPOGRAPHY[f];
  const zone = computeMomentZone(f);
  const columns = computeMomentColumns(f);
  const leadPx = computeLeadPx(HERO_LADDER_PX[f][4], f);
  out.formats[f] = {
    width: FORMAT_DIMENSIONS[f].width,
    height: FORMAT_DIMENSIONS[f].height,
    sourceMinPx: t.sourceMinPx,
    leadMinPx: t.leadMinPx,
    stackGapPx: computeStackGapPx(leadPx),
    leadAtRung5: leadPx,
    watermarkFontSizePx: t.watermarkFontSizePx,
    lineBudgetPx: computeLineBudgetPx(f),
    zoneTop: zone.topFraction,
    zoneBottom: zone.bottomFraction,
    centreFraction: computeMomentCentreFraction(f),
    tallestMomentPx: computeTallestMomentPx(f),
    maxStackPx: computeMaxStackPx(f),
    columnLeft: columns.leftPx,
    columnRight: columns.rightPx,
    watermarkQuietTopPct: computeWatermarkQuietTopPct(f),
    watermarkRestingTopPct: WATERMARK_RESTING_TOP_PCT[f],
    safeAreaTop: SAFE_AREA[f].top,
    safeAreaBottom: SAFE_AREA[f].bottom,
    safeAreaSide: SAFE_AREA[f].side,
    scrimPlateau: computeScrimPlateau(f, 300),
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


@pytest.mark.parametrize("fmt", FORMATS)
def test_frame_dimensions_match(tokens: dict, fmt: str) -> None:
    """The verifier infers the render scale from frame width ÷ nominal width.

    A wrong nominal width silently rescales every geometric check.
    """
    expected = (tokens["formats"][fmt]["width"], tokens["formats"][fmt]["height"])
    assert FORMAT_DIMENSIONS[fmt] == expected


class TestMomentZoneParity:
    """The rows the verifier searches must be the rows the renderer paints.

    `computeMomentZone` derives them from the type scale and the optical centre, so they
    move whenever any display size changes — which makes them exactly the kind of number
    a transcription gets wrong silently.
    """

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_transcribed_fractions_match(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        transcribed = MOMENT_ZONE_FRACTION[fmt]
        assert transcribed["top"] == pytest.approx(values["zoneTop"], abs=0.001)
        assert transcribed["bottom"] == pytest.approx(values["zoneBottom"], abs=0.001)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_matches_the_renderer_at_full_scale(
        self, tokens: dict, fmt: str
    ) -> None:
        values = tokens["formats"][fmt]
        top, bottom = moment_zone(values["width"], values["height"], fmt)  # type: ignore[arg-type]
        assert top == pytest.approx(values["zoneTop"] * values["height"], abs=1)
        assert bottom == pytest.approx(values["zoneBottom"] * values["height"], abs=1)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_matches_at_half_scale(self, tokens: dict, fmt: str) -> None:
        """Proof renders use `--scale=0.5`; the zone must follow.

        Verified against the TypeScript fraction rather than against Python's own
        full-scale answer, so a scaling bug and a transcription bug cannot cancel out.
        """
        values = tokens["formats"][fmt]
        width, height = values["width"] // 2, values["height"] // 2
        top, bottom = moment_zone(width, height, fmt)  # type: ignore[arg-type]
        assert top == pytest.approx(values["zoneTop"] * height, abs=1)
        assert bottom == pytest.approx(values["zoneBottom"] * height, abs=1)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_fits_the_tallest_legal_moment(self, tokens: dict, fmt: str) -> None:
        """The zone is sized for the tallest arrangement, not the usual one.

        A figure with a two-line label and a source line is rare and permitted. A zone
        sized for a statement clips its top, and the verifier then measures a partial
        block — reporting a plausible line count and a wrong extent.
        """
        values = tokens["formats"][fmt]
        top, bottom = moment_zone(values["width"], values["height"], fmt)  # type: ignore[arg-type]
        assert bottom - top >= values["tallestMomentPx"] - 1

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_is_centred_on_the_optical_centre(
        self, tokens: dict, fmt: str
    ) -> None:
        """The zone grows about the centre, so the centre must sit in its middle."""
        values = tokens["formats"][fmt]
        middle = (values["zoneTop"] + values["zoneBottom"]) / 2
        assert middle == pytest.approx(values["centreFraction"], abs=0.002)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_sits_inside_the_frame(self, tokens: dict, fmt: str) -> None:
        """A zone partly outside the frame silently truncates every measurement."""
        values = tokens["formats"][fmt]
        top, bottom = moment_zone(values["width"], values["height"], fmt)  # type: ignore[arg-type]
        assert 0 <= top < bottom <= values["height"]

    def test_vertical_clears_the_platform_ui_strip(self, tokens: dict) -> None:
        """The lowest fifth of a vertical frame is overlaid by the platform's own UI.

        Checked only for vertical: landscape reserves a uniform 8% for a thin
        auto-hiding control bar, and asserting the same rule there would be asserting a
        constraint that does not exist.
        """
        values = tokens["formats"]["vertical"]
        assert values["zoneBottom"] < 1 - values["safeAreaBottom"]

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_clears_the_top_safe_area(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        assert values["zoneTop"] > values["safeAreaTop"]


class TestMomentColumnParity:
    """The anchor column is the strongest invariant the verifier has.

    Every line of every moment shares it, so a wrong transcription turns the check that
    catches centred text into one that rejects correct text.
    """

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_transcribed_columns_match(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        transcribed = MOMENT_COLUMNS_PX[fmt]
        assert transcribed["left"] == pytest.approx(values["columnLeft"], abs=0.5)
        assert transcribed["right"] == pytest.approx(values["columnRight"], abs=0.5)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_columns_scale_with_the_frame(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        left, right = moment_columns(values["width"] // 2, fmt)  # type: ignore[arg-type]
        assert right == pytest.approx(values["columnRight"] / 2, abs=0.5)
        assert left == pytest.approx(values["columnLeft"] / 2, abs=0.5)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_anchor_is_inside_the_side_safe_area(
        self, tokens: dict, fmt: str
    ) -> None:
        """Type on the safe-area boundary reads as touching the edge on a phone."""
        values = tokens["formats"][fmt]
        assert values["columnRight"] <= values["width"] * (1 - values["safeAreaSide"] / 2)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_column_width_is_the_line_budget(self, tokens: dict, fmt: str) -> None:
        """Measurement and paint must agree, or a fitted line still overflows.

        The line breaker measures against `computeLineBudgetPx`; the component paints
        into the span between the columns. If the budget were wider, a line that fits by
        measurement would overflow the column it lands in.
        """
        values = tokens["formats"][fmt]
        span = values["columnRight"] - values["columnLeft"]
        assert values["lineBudgetPx"] == pytest.approx(span, abs=1)


class TestScrimParity:
    """The scrim is where the verifier's thresholds come from, not from the footage.

    `SCRIM_CEILING` and `SCRIM_GUARANTEED_CONTRAST` are both derived from
    `SCRIM.peakAlpha`. If the alpha is lowered for a design reason and these are not
    revisited, the ceiling starts admitting footage as ink and the contrast floor starts
    asserting a guarantee the scrim no longer provides — the failure the floor exists to
    detect becomes undetectable.
    """

    def test_the_ink_ceiling_is_above_what_the_scrim_can_present(
        self, tokens: dict
    ) -> None:
        composited = 255 * (1 - tokens["scrimPeakAlpha"])
        assert SCRIM_CEILING > composited, (
            f"the scrim presents up to {composited:.1f}, so a ceiling of "
            f"{SCRIM_CEILING} admits clipped footage as ink"
        )

    def test_the_ink_ceiling_is_below_every_palette_ink(self, tokens: dict) -> None:
        """Both sides of the discrimination, asserted against the real palette.

        The secondary ink is the tightest: its maximum channel is 214 against a ceiling
        of 95.
        """
        for name in ("ink", "inkSecondary", "accent"):
            channels = _hex_channels(tokens["palette"][name])
            assert max(channels) > SCRIM_CEILING, f"{name} would not register as ink"

    def test_the_guaranteed_contrast_holds_for_every_ink(self, tokens: dict) -> None:
        """The floor is arithmetic about the scrim, not a hope about the footage.

        Computed here the same way the design was: composite clipped white under the
        scrim, then measure each ink against that surface. The weakest is the accent.
        """
        import numpy as np

        background = np.array([[[255 * (1 - tokens["scrimPeakAlpha"])] * 3]])
        background_l = float(relative_luminance(background)[0, 0])

        worst = min(
            (
                float(relative_luminance(np.array([[_hex_channels(tokens["palette"][name])]]))[0, 0])
                + 0.05
            )
            / (background_l + 0.05)
            for name in ("ink", "inkSecondary", "accent")
        )
        assert worst >= SCRIM_GUARANTEED_CONTRAST, (
            f"the weakest ink measures {worst:.2f}:1 against the scrim's worst surface, "
            f"below the {SCRIM_GUARANTEED_CONTRAST}:1 the verifier asserts"
        )

    def test_the_accent_is_separable_from_the_neutral_inks(self, tokens: dict) -> None:
        """`accent_mask` uses a 34 L-infinity tolerance; the inks must clear it.

        With headroom, since a tolerance that only just separates them turns encoder
        noise into a misidentified hero.
        """
        accent = _hex_channels(tokens["palette"]["accent"])
        for name in ("ink", "inkSecondary"):
            other = _hex_channels(tokens["palette"][name])
            distance = max(abs(a - b) for a, b in zip(accent, other))
            assert distance > 34 * 2, f"{name} is only {distance} from the accent"


@pytest.mark.parametrize("fmt", FORMATS)
def test_the_line_ink_floor_is_the_smallest_painted_size(tokens: dict, fmt: str) -> None:
    """A run of ink must clear one em of the *smallest* type, not a nominal size.

    The source line's size is no longer a fixed token — it derives from the lead
    (`SOURCE_RATIO`, floored at `sourceMinPx`) — so the parity check pins the floor
    the source line can never fall below, which is the smallest type any moment
    can paint.
    """
    assert MIN_LINE_PX[fmt] == tokens["formats"][fmt]["sourceMinPx"]


class TestWatermarkClearance:
    """The watermark's quiet position must clear the moment zone in both formats.

    This is not hypothetical. The quiet position was once a hard-coded 75% of frame
    height, which cleared the old caption band in vertical and landed inside it in
    landscape — the mark overlapped the first line of every landscape subtitle. The
    geometry has changed completely since, and the constraint has not.
    """

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_verifier_searches_where_the_renderer_draws(
        self, tokens: dict, fmt: str
    ) -> None:
        """`WATERMARK_TOP_FRACTION` must match the component's own positions.

        The verifier searches a band of ±5% around these. Drift past that window and
        `find_watermark` reports the mark missing on a correct render — or, worse, finds
        it at a position nobody intended and calls that a pass.
        """
        values = tokens["formats"][fmt]
        expected = WATERMARK_TOP_FRACTION[fmt]

        assert expected["quiet"] == pytest.approx(
            values["watermarkQuietTopPct"] / 100, abs=0.005
        )
        assert expected["resting"] == pytest.approx(
            values["watermarkRestingTopPct"] / 100, abs=0.005
        )

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_quiet_position_is_above_the_zone(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        quiet = values["watermarkQuietTopPct"]
        assert quiet < values["zoneTop"] * 100, (
            f"{fmt}: the quiet watermark at {quiet:.1f}% is inside the moment zone, "
            f"which starts at {values['zoneTop'] * 100:.1f}%"
        )

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_bloom_scale_cannot_reach_the_zone(self, tokens: dict, fmt: str) -> None:
        """The mark scales to 1.15 about its centre, so half the growth goes up.

        Clearance has to exceed that growth or the bloom — the one moment the mark is
        most visible — touches the type.
        """
        values = tokens["formats"][fmt]
        half_growth_pct = (
            100 * 0.5 * 0.15 * values["watermarkFontSizePx"] / values["height"]
        )
        assert values["watermarkQuietTopPct"] + half_growth_pct < values["zoneTop"] * 100

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_resting_position_is_above_the_zone(self, tokens: dict, fmt: str) -> None:
        """After migration the mark must still never overlap a moment."""
        values = tokens["formats"][fmt]
        assert values["watermarkRestingTopPct"] < values["zoneTop"] * 100

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_mark_migrates_upward(self, tokens: dict, fmt: str) -> None:
        """The resting position must be above the quiet one, not below.

        `interpolate` accepts either direction, so a swap produces a mark that drifts
        down into the type over the runtime rather than out of the way.
        """
        values = tokens["formats"][fmt]
        assert values["watermarkRestingTopPct"] < values["watermarkQuietTopPct"]

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_quiet_position_stays_inside_the_frame(
        self, tokens: dict, fmt: str
    ) -> None:
        """A clearance large enough to push the mark off the top would go unnoticed.

        `computeWatermarkQuietTopPct` clamps at the resting position, so this checks the
        clamp is doing its job rather than the arithmetic happening to stay positive.
        """
        values = tokens["formats"][fmt]
        assert 0 < values["watermarkQuietTopPct"] < 100


def _hex_channels(value: str) -> tuple[int, int, int]:
    """`#RRGGBB` → channels. The palette states its colours as hex strings."""
    text = value.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


class TestPacingTokenParity:
    """The pipeline's reading model must be the renderer's, character for character.

    `lib/persian_moments.py` gates moments in the pipeline, before any browser runs;
    the values it charges — fixation, block cost, floors, the opening deadline —
    exist in `tokens.ts` as well, and a drift between the two copies makes the gate
    and the renderer disagree about whether a moment is readable. That is exactly
    the transcription failure mode the zone tests above exist for, applied to time
    instead of space.
    """

    def test_reading_constants_match(self, tokens: dict) -> None:
        from lib.persian_moments import (
            FIXATION_SECONDS,
            MAX_SECONDS,
            MIN_GAP_SECONDS,
            MIN_SECONDS,
            OPENING_MAX_START_SECONDS,
            READ_CPS,
            BLOCK_SECONDS,
        )

        assert READ_CPS == tokens["readCps"]
        assert FIXATION_SECONDS == tokens["fixationSeconds"]
        assert BLOCK_SECONDS == tokens["blockSeconds"]
        assert MIN_SECONDS == tokens["minSeconds"]
        assert MAX_SECONDS == tokens["maxSeconds"]
        assert MIN_GAP_SECONDS == tokens["minGapSeconds"]
        assert OPENING_MAX_START_SECONDS == tokens["openingMaxStartSeconds"]

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_rhythm_gap_is_the_tokens_derivation(self, tokens: dict, fmt: str) -> None:
        """`measure_stack_rhythm` compares against `lead × STACK_GAP_RATIO`.

        The verifier must derive its expected gap the way the renderer does, from
        the lead size at a known rung — pinned here against the same rung the
        verifier's callers are told to use.
        """
        values = tokens["formats"][fmt]
        expected = round(values["leadAtRung5"] * tokens["stackGapRatio"])
        assert values["stackGapPx"] == expected
        assert STACK_GAP_RATIO == tokens["stackGapRatio"]
        assert expected_stack_gap_px(values["leadAtRung5"]) == expected

    def test_the_hook_rhythm_gap_follows_the_qualifier(self, tokens: dict) -> None:
        """A claim+qualifier hook's gap derives from the tail, not the lead.

        Mirrors `stackGapPxForMoment(leadPx, tailPx, claimQualifier=True)` in
        `layout.ts`: the gap sits between the claim and the qualifier, so the
        expectation is `round(tail × STACK_GAP_RATIO)`. The tail size is passed
        through (fitted, never re-derived in Python) so this pins the branch —
        a future divergence between the two sides fails here rather than as a
        spurious rhythm flag on moment 1. Vertical only: the approved hook and
        its fitted sizes (hero 93, tail 68, gap 37) are pinned for vertical by
        `test_persian_flat_hook.py`.
        """
        from lib.persian_moments import build_moments, is_claim_qualifier_hook

        import json as _json

        edit_path = REPO_ROOT / "projects" / "coffee-hormones-fa" / "artifacts" / "edit_decisions.json"
        edit = _json.loads(edit_path.read_text(encoding="utf-8"))
        first = edit["persian"]["moments"][0]
        assert first["kind"] == "hook"
        assert first["id"] == "moment-1"

        built = build_moments([first])
        assert is_claim_qualifier_hook(built[0]) is True
        # Fitted sizes for the approved hook: hero 93, lead 36 (=computeLeadPx),
        # tail 68 (=round(93 × 0.73)). The gap derives from the tail.
        assert expected_stack_gap_px(
            36.0, tail_px=68.0, claim_qualifier=True
        ) == round(68.0 * tokens["stackGapRatio"]) == 37
        # The ordinary branch must not collapse onto the hook one: the lead
        # derivation for the same moment is 20px, a different design.
        assert expected_stack_gap_px(36.0) == round(36.0 * tokens["stackGapRatio"]) == 20
        # The hook branch refuses to guess without the fitted tail: a silent
        # fallback to the lead derivation is the wrong design (20 vs 37).
        with pytest.raises(ValueError):
            expected_stack_gap_px(36.0, claim_qualifier=True)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_ladder_bottom_is_the_smallest_hero(self, tokens: dict, fmt: str) -> None:
        """At the ladder's floor the lead clamps to its minimum, and derives above it.

        Pinned because the size floors and the ratio interact: the lead must never
        exceed `LEAD_MAX_RATIO` of its hero and never fall below `leadMinPx`, and
        the pin makes a change to either visible in this file rather than first in
        a render.
        """
        values = tokens["formats"][fmt]
        assert 0 < values["sourceMinPx"] < values["leadMinPx"] <= values["leadAtRung5"]
        # At the bottom rung the lead should sit at or near its floor…
        assert values["leadAtRung5"] <= values["leadMinPx"] * 1.05


class TestScrimPlateauParity:
    """The plateau is the per-moment darkened band; the zone is its envelope.

    The verifier must measure only rows the scrim guarantees (``peakAlpha``).
    A transcription that drifts — wrong margin, wrong centre, missing scale —
    puts bright footage inside the measured band and revives the false-anchor
    failure. Pinned against ``computeScrimPlateau`` with the same derivation.
    """

    def test_the_plateau_margin_matches(self, tokens: dict) -> None:
        assert SCRIM_PLATEAU_MARGIN_PX == tokens["scrimPlateauMarginPx"]

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_plateau_centre_matches(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        assert moment_centre_fraction(fmt) == pytest.approx(values["centreFraction"], abs=0.001)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_plateau_matches_the_renderer_at_nominal(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        width, height = values["width"], values["height"]
        stack = 300.0
        top, bottom = scrim_plateau(width, height, fmt, stack)  # type: ignore[arg-type]
        ts = values["scrimPlateau"]
        assert top == pytest.approx(ts["topFraction"] * height, abs=1)
        assert bottom == pytest.approx(ts["bottomFraction"] * height, abs=1)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_plateau_scales_with_the_frame(self, tokens: dict, fmt: str) -> None:
        """Proof renders at 0.5× must scale the plateau with the frame."""
        values = tokens["formats"][fmt]
        width, height = values["width"] // 2, values["height"] // 2
        stack = 300.0
        top, bottom = scrim_plateau(width, height, fmt, stack)  # type: ignore[arg-type]
        # Compare against fractions, not against nominal px /2, so scale and
        # transcription bugs cannot cancel.
        frac_top = top / height
        frac_bottom = bottom / height
        ts = values["scrimPlateau"]
        assert frac_top == pytest.approx(ts["topFraction"], abs=0.01)
        assert frac_bottom == pytest.approx(ts["bottomFraction"], abs=0.01)

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_plateau_is_inside_the_zone(self, tokens: dict, fmt: str) -> None:
        """A moment shorter than the tallest legal one: its plateau sits well inside."""
        values = tokens["formats"][fmt]
        width, height = values["width"], values["height"]
        # 300px is well below the budget (~802/562)
        top, bottom = scrim_plateau(width, height, fmt, 300.0)  # type: ignore[arg-type]
        zone_top, zone_bottom = values["zoneTop"] * height, values["zoneBottom"] * height
        assert top > zone_top
        assert bottom < zone_bottom

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_zone_truly_envelopes_the_tallest_plateau(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        width, height = values["width"], values["height"]
        tallest = values["tallestMomentPx"]
        top, bottom = scrim_plateau(width, height, fmt, float(tallest))  # type: ignore[arg-type]
        zone_top, zone_bottom = values["zoneTop"] * height, values["zoneBottom"] * height
        # Tallest plateau plus margin may extend just beyond the zone; the zone
        # is the ink budget, the plateau adds 28px margin, so expect within 28.
        assert top >= zone_top - SCRIM_PLATEAU_MARGIN_PX - 1
        assert bottom <= zone_bottom + SCRIM_PLATEAU_MARGIN_PX + 1
