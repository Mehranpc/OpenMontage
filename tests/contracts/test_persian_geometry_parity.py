"""Python ↔ TypeScript parity for the Persian layout geometry.

`lib/persian_verify.py` measures rendered frames against the geometry it believes the
renderer used. That belief is a transcription of `tokens.ts` — a second copy of numbers
whose first copy is in TypeScript. A transcription that drifts makes the verifier worse
than useless: it computes a subtitle band that is not where the subtitle is, finds no
text, and reports either a false failure or, if the band still clips part of the panel,
a false pass on partial text.

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
    NOMINAL_FONT_PX,
    PANEL_WIDTH_FRACTION,
    WATERMARK_TOP_FRACTION,
    subtitle_band,
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
  FORMAT_DIMENSIONS, TYPOGRAPHY, GLASS, SAFE_AREA,
  WATERMARK_RESTING_TOP_PCT, WATERMARK_QUIET_CLEARANCE_PCT,
  computeLineBudgetPx, computeSubtitleBandTopFraction, computeWatermarkQuietTopPct,
} from "./src/persian/tokens.ts";

const formats = ["vertical", "landscape"];
const out = {
  glassMaxWidthFraction: GLASS.maxWidthFraction,
  watermarkQuietClearancePct: WATERMARK_QUIET_CLEARANCE_PCT,
  formats: {},
};
for (const f of formats) {
  const t = TYPOGRAPHY[f];
  out.formats[f] = {
    width: FORMAT_DIMENSIONS[f].width,
    height: FORMAT_DIMENSIONS[f].height,
    subtitleFontSizePx: t.subtitleFontSizePx,
    subtitleLineHeight: t.subtitleLineHeight,
    glassPaddingV: t.glassPaddingPx[0],
    glassPaddingH: t.glassPaddingPx[1],
    subtitleBottomPx: t.subtitleBottomPx,
    maxLines: t.maxLines,
    maxLinesEscalated: t.maxLinesEscalated,
    watermarkFontSizePx: t.watermarkFontSizePx,
    lineBudgetPx: computeLineBudgetPx(f),
    bandTopFraction: computeSubtitleBandTopFraction(f),
    watermarkQuietTopPct: computeWatermarkQuietTopPct(f),
    watermarkRestingTopPct: WATERMARK_RESTING_TOP_PCT[f],
    safeAreaBottom: SAFE_AREA[f].bottom,
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


@pytest.mark.parametrize("fmt", FORMATS)
def test_panel_width_fraction_matches(tokens: dict, fmt: str) -> None:
    """The envelope check is this number; drift makes it test the wrong width."""
    assert PANEL_WIDTH_FRACTION == pytest.approx(tokens["glassMaxWidthFraction"])


@pytest.mark.parametrize("fmt", FORMATS)
def test_nominal_font_size_matches(tokens: dict, fmt: str) -> None:
    """Used as the per-line ink floor, so it scales the line-detection threshold."""
    assert NOMINAL_FONT_PX[fmt] == tokens["formats"][fmt]["subtitleFontSizePx"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_subtitle_band_matches_the_renderer_at_full_scale(
    tokens: dict, fmt: str
) -> None:
    """The band Python computes is the band TypeScript would.

    Compared against `computeSubtitleBandTopFraction`, which the watermark also uses,
    so this single assertion covers both consumers of the geometry.
    """
    values = tokens["formats"][fmt]
    top, bottom = subtitle_band(values["width"], values["height"], fmt)  # type: ignore[arg-type]

    assert bottom == values["height"] - values["subtitleBottomPx"]
    assert top == pytest.approx(values["bandTopFraction"] * values["height"], abs=1)


@pytest.mark.parametrize("fmt", FORMATS)
def test_subtitle_band_matches_at_half_scale(tokens: dict, fmt: str) -> None:
    """Proof renders use `--scale=0.5`; the band must follow.

    Verified against the TypeScript fraction rather than against Python's own
    full-scale answer, so a scaling bug and a transcription bug cannot cancel out.
    """
    values = tokens["formats"][fmt]
    width, height = values["width"] // 2, values["height"] // 2
    top, bottom = subtitle_band(width, height, fmt)  # type: ignore[arg-type]

    assert top == pytest.approx(values["bandTopFraction"] * height, abs=1)
    assert bottom == pytest.approx(height - values["subtitleBottomPx"] / 2, abs=1)


@pytest.mark.parametrize("fmt", FORMATS)
def test_band_height_accounts_for_the_escalated_line_cap(
    tokens: dict, fmt: str
) -> None:
    """The band must fit the tallest legal panel, not the usual one.

    A four-line cue is rare but permitted. A band sized for three lines clips its top
    line, and the verifier then measures a partial panel — reporting a plausible line
    count and a wrong extent.
    """
    values = tokens["formats"][fmt]
    top, bottom = subtitle_band(values["width"], values["height"], fmt)  # type: ignore[arg-type]

    tallest = (
        2 * values["glassPaddingV"]
        + values["maxLinesEscalated"]
        * values["subtitleFontSizePx"]
        * values["subtitleLineHeight"]
    )
    assert bottom - top == pytest.approx(tallest, abs=1)


@pytest.mark.parametrize("fmt", FORMATS)
def test_the_band_sits_inside_the_frame(tokens: dict, fmt: str) -> None:
    """A band partly outside the frame silently truncates every measurement."""
    values = tokens["formats"][fmt]
    top, bottom = subtitle_band(values["width"], values["height"], fmt)  # type: ignore[arg-type]
    assert 0 <= top < bottom <= values["height"]


class TestWatermarkClearance:
    """The watermark's quiet position must clear the subtitle band in both formats.

    This is not hypothetical. The quiet position was a hard-coded 75% of frame height.
    In vertical the band starts at 52%, so 75% was clear. In landscape the panel sits
    110px from the bottom rather than 590px, so the band starts at 68% and 75% landed
    *inside* it — the mark overlapped the first line of every landscape subtitle. The
    check that found it was a line-count of 2 on a one-line cue.
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
    def test_the_quiet_position_is_above_the_band(self, tokens: dict, fmt: str) -> None:
        values = tokens["formats"][fmt]
        quiet = values["watermarkQuietTopPct"]

        assert quiet < values["bandTopFraction"] * 100, (
            f"{fmt}: the quiet watermark at {quiet:.1f}% is inside the subtitle band, "
            f"which starts at {values['bandTopFraction'] * 100:.1f}%"
        )

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_bloom_scale_cannot_reach_the_band(self, tokens: dict, fmt: str) -> None:
        """The mark scales to 1.15 about its centre, so half the growth goes up.

        Clearance has to exceed that growth or the bloom — the one moment the mark is
        most visible — touches the panel.
        """
        values = tokens["formats"][fmt]
        quiet = values["watermarkQuietTopPct"]

        half_growth_px = 0.5 * 0.15 * values["watermarkFontSizePx"]
        half_growth_pct = 100 * half_growth_px / values["height"]

        assert quiet + half_growth_pct < values["bandTopFraction"] * 100, (
            f"{fmt}: the bloomed watermark reaches into the subtitle band"
        )

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_resting_position_is_above_the_band(
        self, tokens: dict, fmt: str
    ) -> None:
        """After migration the mark must still never overlap a subtitle."""
        values = tokens["formats"][fmt]
        assert values["watermarkRestingTopPct"] < values["bandTopFraction"] * 100

    @pytest.mark.parametrize("fmt", FORMATS)
    def test_the_mark_migrates_upward(self, tokens: dict, fmt: str) -> None:
        """The resting position must be above the quiet one, not below.

        `interpolate` accepts either direction, so a swap produces a mark that drifts
        down into the panel over the runtime rather than out of the way.
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


@pytest.mark.parametrize("fmt", FORMATS)
def test_line_budget_fits_inside_the_panel(tokens: dict, fmt: str) -> None:
    """The measured text budget must be narrower than the box the text lands in.

    Measuring against a budget wider than the panel is the classic overflow: it shows
    up only on cues close to the limit, which is exactly where it matters.
    """
    values = tokens["formats"][fmt]
    panel_inner = (
        values["width"] * tokens["glassMaxWidthFraction"] - 2 * values["glassPaddingH"]
    )
    assert values["lineBudgetPx"] <= panel_inner
    assert values["lineBudgetPx"] > 0


@pytest.mark.parametrize("fmt", FORMATS)
def test_the_panel_sits_inside_the_bottom_safe_area(tokens: dict, fmt: str) -> None:
    """Platform chrome overlays the bottom of the frame.

    Vertical reserves 20% for the Reels/Shorts caption and action rail. A panel whose
    bottom edge intrudes there is covered by the platform's own UI on the phone, where
    nobody previews it.
    """
    values = tokens["formats"][fmt]
    reserved = values["safeAreaBottom"] * values["height"]
    assert values["subtitleBottomPx"] >= reserved, (
        f"{fmt}: the panel's bottom edge is {values['subtitleBottomPx']}px from the "
        f"frame bottom, inside the {reserved:.0f}px reserved for platform UI"
    )
