"""Frame-level verification for Persian renders.

The compose stage has exactly one check worth doing: did the Persian text actually
render correctly? A completed render proves the props were well-formed and nothing
more. Tofu boxes, reversed reading order, and text past the panel edge all produce a
perfectly valid MP4 of the right duration.

## Why this is harder than it looks

The obvious detector is a brightness threshold:

    ink = frame.max(axis=2) > 200          # "find the bright text"

Over dark footage this works. Over *bright* footage — a sunlit table, an overexposed
sky — it selects the footage, the measured extent becomes the whole frame, and the
check reports text overflowing the panel while the text is perfectly placed. It fails
precisely when the footage is most likely to cause a real contrast problem, so the
false alarm hides the true one. This was observed, not hypothesized: eight cues from a
real render, seven over dark clips, one over a bright one, and the eighth was the only
"failure".

Two attempted fixes also failed, and both are worth recording because they look
sounder than they are:

* **Find the panel by its brightness dip.** The panel darkens what it covers, so it
  should appear as a dip in row-mean brightness. But it shrink-wraps its text — a short
  cue's panel is narrow — so a row-mean over the full width is dominated by the footage
  *beside* it. Over a bright clip the dip vanishes into the footage's own variation.

* **Per-column darkening ratio.** Compare each column inside the band against the same
  column above it; a covered column should drop by the panel's alpha. This fails on the
  frames where the camera move means the footage above a column is not what would have
  been under it.

## What actually works

Two facts about the composition, neither of which depends on the footage:

1. **The band is deterministic.** `subtitleBottomPx` and the type scale come from
   `tokens.ts`, so the rows the subtitle can occupy are computable from the format and
   the frame's own width. No detection needed.

2. **The ink is near-white or the highlight yellow, and nothing else is.** Subtitle
   text is `#FFFFFF` and the highlight is `#FFEA00`. Requiring the *minimum* channel to
   be near 255 — not the maximum — excludes footage highlights, which are almost never
   neutral at that level. Measured on the bright-footage frame: 12.4% of the glyph area
   passes `min >= 235`, against 0.0% of the footage above it.

3. **A column crossing the panel has gaps darker than the panel can present.** Colour
   alone cannot separate the one remaining case: clipped white footage is byte-identical
   to white text. Structure can. A column through the panel contains the spaces between
   and around glyphs, which are capped at 149; a column of blown-out footage beside the
   panel contains nothing that dark. So columns are gated on containing at least one
   pixel below the ceiling before their ink counts.

A per-row density floor removes the few specular pixels that do pass — but by *run
total*, not per row: one em of ink per run of rows is scale-correct for both a 540px
proof render and a 1920px landscape frame, where no single width fraction is.

## What the contrast number means here

The glass panel composites 45% of `rgba(20,20,20)` over whatever is behind it, so the
brightest surface it can ever present is `0.55·255 + 0.45·20 = 149`, and white text on
that measures 2.99:1. That makes the floor diagnostic rather than advisory: a reading
below it cannot be "the grade is too weak for this footage", because no footage can
produce it through a working panel. It means the panel did not render.

All functions take a decoded RGB frame as an `(H, W, 3)` integer array. Nothing loads or
writes files — the caller does that — so this stays usable from a director skill, a
test, or an interactive session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np

PersianFormat = Literal["vertical", "landscape"]

#: Mirrors `FORMAT_DIMENSIONS` in `remotion-composer/src/persian/tokens.ts`.
FORMAT_DIMENSIONS: dict[str, tuple[int, int]] = {
    "vertical": (1080, 1920),
    "landscape": (1920, 1080),
}

#: Mirrors the subtitle geometry in `TYPOGRAPHY`. Only the fields that determine which
#: rows the subtitle can occupy: bottom offset, vertical padding, font size, line
#: height, and the escalated line cap.
SUBTITLE_GEOMETRY: dict[str, dict[str, float]] = {
    "vertical": {
        "bottom_px": 590,
        "padding_v_px": 20,
        "font_px": 52,
        "line_height": 1.4,
        "max_lines": 4,
    },
    "landscape": {
        "bottom_px": 110,
        "padding_v_px": 18,
        "font_px": 46,
        "line_height": 1.45,
        "max_lines": 3,
    },
}

#: Fraction of frame width the panel may occupy — `GLASS.maxWidthFraction`. Text
#: outside this envelope means the layout measured against the wrong font.
PANEL_WIDTH_FRACTION = 0.85

#: Where the watermark sits in each phase, as a fraction of frame height. Mirrors
#: `WATERMARK_RESTING_TOP_PCT` and `computeWatermarkQuietTopPct` in `tokens.ts`; both
#: are pinned against the TypeScript source by
#: `tests/contracts/test_persian_geometry_parity.py`.
#:
#: The quiet position is per-format because the subtitle band is. A single value was
#: below the band in vertical and inside it in landscape.
WATERMARK_TOP_FRACTION: dict[str, dict[str, float]] = {
    "vertical": {"quiet": 0.46, "resting": 0.15},
    "landscape": {"quiet": 0.62, "resting": 0.08},
}

#: Minimum channel value for a pixel to count as white text. High, and deliberately on
#: the *minimum* channel: that is what separates neutral glyphs from bright footage.
WHITE_MIN_CHANNEL = 225

#: Row gap, in pixels, that separates two lines of text.
LINE_GAP_PX = 4

#: Nominal font size per format, from `TYPOGRAPHY`. A run of ink rows must carry at
#: least this many ink pixels in total to count as a line of text: one em of ink is
#: less than a single Persian letter, so no real line falls below it, while a specular
#: highlight on wet asphalt — a handful of pixels — does.
NOMINAL_FONT_PX = {"vertical": 52, "landscape": 46}

#: Brightest value the panel can present, with a small margin for JPEG ringing at
#: glyph edges. See `PANEL_GUARANTEED_CONTRAST` for the arithmetic: 45% of
#: rgba(20,20,20) over fully clipped white composites to 149.
#:
#: Used as a *column* gate. A column that passes through the panel must contain at
#: least one pixel at or below this value — the gaps between and around glyphs. A
#: column of blown-out footage beside the panel contains none, which is what separates
#: the two cases when colour alone cannot: pure white footage is the same RGB as white
#: text.
PANEL_COMPOSITING_CEILING = 165

#: Fraction of the band's columns that must pass the ceiling test before the column
#: gate is applied.
#:
#: The gate assumes a panel exists. When it does not — text painted straight onto a
#: bright clip — almost no column passes, and gating would suppress the text entirely
#: and report "no text found" for a frame whose actual fault is a missing panel. Below
#: this fraction the gate is skipped and the missing panel is reported instead, which
#: is both true and the more useful thing to say.
MIN_PANEL_COLUMN_FRACTION = 0.5

#: Contrast the glass panel guarantees. The panel composites 45% of rgba(20,20,20)
#: over whatever is behind it, so even fully clipped white footage presents at most
#: 0.55·255 + 0.45·20 = 149, and white text on that is 2.99:1.
#:
#: This makes the check sharper than a generic accessibility threshold: a reading below
#: this floor is not "the grade is too weak", it is "the panel did not render", because
#: no footage can produce it through a working panel.
PANEL_GUARANTEED_CONTRAST = 2.99

#: Below this, contrast is comfortable rather than merely legible. Reported as advice,
#: not as a failure — the panel is working, the footage under it is just bright.
COMFORTABLE_CONTRAST = 4.5

# --- Watermark detection -----------------------------------------------------------
#
# The watermark has no panel behind it, so none of the subtitle thresholds apply. See
# `find_watermark` for why appearance-based detection does not work here at all.

#: Per-pixel channel difference that counts as changed when comparing a frame against
#: the same frame rendered without the watermark. Above PNG-identical, below anything
#: the mark itself produces: measured differences inside the mark reach 161.
DIFF_THRESHOLD = 12

#: Ink threshold for the footage-free fallback. The mark rests at 0.6 opacity over the
#: composition's near-black fill, which composites to about 153.
WATERMARK_INK_THRESHOLD = 60

#: Median band brightness above which the fallback refuses to run, because the band
#: contains footage rather than the composition's own background.
FOOTAGE_FREE_CEILING = 40

#: Fraction of frame width a row must carry to be part of the watermark.
#:
#: A per-row floor rather than a per-run total, because the noise here is not scattered
#: pixels but a faint *outline* of the mark's own shadow reaching tens of rows beyond
#: the glyphs, contiguous with them — so a run-total filter keeps all of it and reports
#: the mark as 95 rows tall instead of 14.
MIN_WATERMARK_ROW_FRACTION = 0.02

#: Fraction of the *strongest* row a row must carry, applied alongside the absolute
#: floor above.
#:
#: The absolute floor alone is not enough. On a 60-second render the shadow halo reached
#: 33 pixels per row against a 2%-of-width floor of 10, and the measured extent grew from
#: 14 rows to 89. The halo scales with the mark, so a relative floor tracks it: at 20% of
#: peak, all four measured pairs — two MP4 renders at different lengths, a lossless
#: still, and a second format — land within 2 rows of the true extent.
MIN_WATERMARK_PEAK_FRACTION = 0.20


def _highlight_mask(frame: np.ndarray) -> np.ndarray:
    """Pixels matching the karaoke highlight `#FFEA00`.

    Needed separately because the highlight is not neutral: its blue channel is near
    zero, so it fails the near-white test that catches the white text.
    """
    return (
        (frame[..., 0] >= 235)
        & (frame[..., 1] >= 200)
        & (frame[..., 1] <= 250)
        & (frame[..., 2] <= 90)
    )


def ink_mask(frame: np.ndarray) -> np.ndarray:
    """Pixels that are subtitle ink: near-white text or the highlight yellow."""
    array = np.asarray(frame, dtype=int)
    near_white = array.min(axis=2) >= WHITE_MIN_CHANNEL
    return near_white | _highlight_mask(array)


def subtitle_band(
    frame_width: int, frame_height: int, fmt: PersianFormat
) -> tuple[int, int]:
    """Rows the subtitle can occupy, computed from the tokens.

    Scales with the frame so a `--scale=0.5` proof render measures correctly: a 540px
    frame in vertical format has every geometric token halved.
    """
    nominal_width = FORMAT_DIMENSIONS[fmt][0]
    scale = frame_width / nominal_width
    geometry = SUBTITLE_GEOMETRY[fmt]

    bottom = int(round(frame_height - geometry["bottom_px"] * scale))
    height = int(
        round(
            (
                2 * geometry["padding_v_px"]
                + geometry["max_lines"] * geometry["font_px"] * geometry["line_height"]
            )
            * scale
        )
    )
    return max(0, bottom - height), min(frame_height, bottom)


def _ink_row_runs(
    row_counts: np.ndarray, *, min_run_ink: int
) -> list[tuple[int, int]]:
    """Group ink rows into lines, discarding runs too faint to be text.

    Filtering by *run total* rather than per-row density is what makes this robust
    across scales. A per-row floor has to be expressed as a fraction of frame width,
    and no single fraction works for both a 540px proof render and a 1920px landscape
    frame: the value that passes a short cue's narrow line at 540px also passes a
    specular highlight at 1920px.

    A run's total ink, compared against one em, is scale-correct by construction — both
    sides scale with the frame — and it matches what is actually being distinguished: a
    line of text versus a few stray bright pixels.
    """
    rows = np.where(row_counts > 0)[0]
    if rows.size == 0:
        return []

    runs: list[tuple[int, int]] = []
    start = previous = int(rows[0])
    for row in rows[1:]:
        row = int(row)
        if row - previous > LINE_GAP_PX:
            runs.append((start, previous))
            start = row
        previous = row
    runs.append((start, previous))

    return [
        (lo, hi) for lo, hi in runs if int(row_counts[lo : hi + 1].sum()) >= min_run_ink
    ]


def relative_luminance(frame: np.ndarray) -> np.ndarray:
    """WCAG relative luminance, per pixel.

    Used rather than a channel mean because contrast ratios are only meaningful in
    these terms, and because a channel mean rates the yellow highlight as dimmer than
    it reads — which would flag a correct design as low contrast.
    """
    channels = np.asarray(frame, dtype=float) / 255.0
    linear = np.where(
        channels <= 0.03928, channels / 12.92, ((channels + 0.055) / 1.055) ** 2.4
    )
    return 0.2126 * linear[..., 0] + 0.7152 * linear[..., 1] + 0.0722 * linear[..., 2]


@dataclass
class TextMeasurement:
    """What was found in one frame's subtitle band."""

    band_rows: tuple[int, int]
    glyph_rows: tuple[int, int] | None
    glyph_columns: tuple[int, int] | None
    glyph_pixels: int
    line_count: int
    centre_offset_px: float | None
    inside_panel_envelope: bool | None
    contrast_ratio: float | None
    problems: list[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return self.glyph_pixels > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "band_rows": list(self.band_rows),
            "glyph_rows": list(self.glyph_rows) if self.glyph_rows else None,
            "glyph_columns": list(self.glyph_columns) if self.glyph_columns else None,
            "glyph_pixels": self.glyph_pixels,
            "line_count": self.line_count,
            "centre_offset_px": self.centre_offset_px,
            "inside_panel_envelope": self.inside_panel_envelope,
            "contrast_ratio": self.contrast_ratio,
            "problems": list(self.problems),
        }


def measure_subtitle_text(
    frame: np.ndarray, fmt: PersianFormat = "vertical"
) -> TextMeasurement:
    """Measure the subtitle text in one frame.

    Reports rather than asserts. A frame sampled mid-entrance legitimately has partial
    opacity and a frame between cues legitimately has no text; only the caller knows
    which frames it chose and what each should contain.

    `problems` carries the faults that are unambiguous whatever the frame's timing:
    text outside the panel envelope, off-centre text, and contrast below the WCAG
    large-text floor.
    """
    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape
    band_top, band_bottom = subtitle_band(width, height, fmt)

    band = array[band_top:band_bottom]
    # Columns that pass through the panel. Blown-out footage is the one case colour
    # cannot separate — clipped white footage is byte-identical to white text — so it
    # is separated structurally instead: a column crossing the panel has glyph gaps
    # below the compositing ceiling, and a column of clipped footage has none.
    #
    # Skipped when hardly any column qualifies, which means there is no panel at all.
    # Gating then would hide the text and report "no text" for a frame whose real
    # fault is the missing panel — the contrast check below says that outright.
    panel_columns = band.max(axis=2).min(axis=0) <= PANEL_COMPOSITING_CEILING
    mask = ink_mask(array)[band_top:band_bottom]
    if panel_columns.mean() >= MIN_PANEL_COLUMN_FRACTION:
        mask = mask & panel_columns[None, :]

    scale = width / FORMAT_DIMENSIONS[fmt][0]
    lines = _ink_row_runs(
        mask.sum(axis=1), min_run_ink=max(4, int(round(NOMINAL_FONT_PX[fmt] * scale)))
    )

    if not lines:
        return TextMeasurement(
            band_rows=(band_top, band_bottom),
            glyph_rows=None,
            glyph_columns=None,
            glyph_pixels=0,
            line_count=0,
            centre_offset_px=None,
            inside_panel_envelope=None,
            contrast_ratio=None,
            problems=[],
        )

    # Restrict to the text rows, so stray ink elsewhere in the band cannot widen the
    # measured extent and produce a false envelope violation.
    text_top, text_bottom = lines[0][0], lines[-1][1]
    text_mask = np.zeros_like(mask)
    for lo, hi in lines:
        text_mask[lo : hi + 1] = mask[lo : hi + 1]

    cols = np.where(text_mask.sum(axis=0) > 0)[0]
    glyph_top, glyph_bottom = band_top + text_top, band_top + text_bottom
    line_count = len(lines)

    centre = (int(cols.min()) + int(cols.max())) / 2
    centre_offset = round(centre - width / 2, 1)

    margin = width * (1 - PANEL_WIDTH_FRACTION) / 2
    inside = bool(cols.min() >= margin - 1 and cols.max() <= width - margin + 1)

    ratio = _measure_contrast(
        array, text_mask, text_top, text_bottom, cols, band_top, band_bottom, glyph_bottom
    )

    problems: list[str] = []
    if not inside:
        problems.append(
            f"text spans x {int(cols.min())}..{int(cols.max())} but the panel envelope "
            f"is {margin:.0f}..{width - margin:.0f} — the layout measured against a "
            "different font than the one that painted, or the panel width token changed"
        )
    # A few px of asymmetry is antialiasing; 2% of width is a broken container.
    if abs(centre_offset) > width * 0.02:
        problems.append(
            f"text centre is {centre_offset:+.0f}px from the frame centre — the panel's "
            "flex centring is not taking effect"
        )
    if ratio is not None and ratio < PANEL_GUARANTEED_CONTRAST:
        problems.append(
            f"contrast {ratio:.2f}:1 is below {PANEL_GUARANTEED_CONTRAST}:1, which the "
            "glass panel guarantees against any footage — the panel did not render, so "
            "the text is sitting directly on the clip"
        )

    return TextMeasurement(
        band_rows=(band_top, band_bottom),
        glyph_rows=(glyph_top, glyph_bottom),
        glyph_columns=(int(cols.min()), int(cols.max())),
        glyph_pixels=int(text_mask.sum()),
        line_count=line_count,
        centre_offset_px=centre_offset,
        inside_panel_envelope=inside,
        contrast_ratio=round(ratio, 2) if ratio is not None else None,
        problems=problems,
    )


def _measure_contrast(
    array: np.ndarray,
    mask: np.ndarray,
    text_top: int,
    text_bottom: int,
    cols: np.ndarray,
    band_top: int,
    band_bottom: int,
    glyph_bottom: int,
) -> float | None:
    """Contrast between the glyphs and the surface they sit on.

    The background sample is the panel's own bottom padding strip, restricted to the
    glyph columns. That strip is glyph-free by construction — it is padding — and it is
    literally the surface behind the text, which no other region can claim: sampling
    dark pixels between glyphs mixes in antialiased edges, and sampling outside the
    panel measures the footage instead of the panel.
    """
    luminance = relative_luminance(array)
    left, right = int(cols.min()), int(cols.max()) + 1

    band_luminance = luminance[band_top:band_bottom]
    glyph_values = band_luminance[text_top : text_bottom + 1, left:right][
        mask[text_top : text_bottom + 1, left:right]
    ]
    if glyph_values.size == 0:
        return None

    strip = luminance[glyph_bottom + 3 : band_bottom - 1, left:right]
    if strip.size == 0:
        return None

    text_l = float(glyph_values.mean())
    background_l = float(np.median(strip))
    return (max(text_l, background_l) + 0.05) / (min(text_l, background_l) + 0.05)


def check_reading_order(
    frame: np.ndarray,
    *,
    highlight_word_index: int,
    word_count: int,
    fmt: PersianFormat = "vertical",
) -> dict[str, Any]:
    """Verify RTL reading order from the highlighted word's position.

    Reversed reading order is one of the two faults that must never ship, and it is
    invisible to every geometric check: «این متن فارسی است» reversed occupies the same
    box, has the same line count, and the same contrast. So this is the only check that
    can catch it, which makes its preconditions worth stating exactly.

    ## What it needs

    **A cue with a highlight phrase.** The signal is the yellow `#FFEA00` of
    `highlightPhrases`, not the karaoke cursor. Karaoke emphasis is scale and glow only —
    deliberately, since colouring the spoken word would fight the highlight and changing
    its weight would reflow the line — so a cue with no highlight phrase has no coloured
    word and nothing to locate. Pass the index of a word inside the highlight phrase.

    **A single-line cue.** Each line is centred independently, so on a two-line cue the
    first word of line 2 sits at the right end of line 2 while its global index is
    halfway through the cue. Global index maps to horizontal position only when there is
    one line. Multi-line cues are refused rather than guessed at.

    **A word that is not near the middle.** Word 0 is rightmost under RTL and leftmost
    under LTR, so an early word carries the signal. A word at the centre of the sentence
    is near the centre of the line under either direction and proves nothing.

    Each of those is checked and reported rather than assumed, because a reading-order
    check that answers confidently from an invalid input is worse than one that declines:
    it certifies the fault it was built to catch.
    """
    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape

    # Restricted to the subtitle band: footage contains yellow. A sunset frame in the
    # 60s proof render produced 37 highlight-coloured pixels spread over rows 177-380,
    # entirely outside the band, which read as a highlight sitting left of centre.
    band_top, band_bottom = subtitle_band(width, height, fmt)
    yellow = np.zeros(array.shape[:2], dtype=bool)
    yellow[band_top:band_bottom] = _highlight_mask(array[band_top:band_bottom])

    if not yellow.any():
        outside = int(_highlight_mask(array).sum())
        return {
            "found": False,
            "reason": "no highlight pixels inside the subtitle band. Either this cue has "
            "no `highlightPhrases` — karaoke emphasis is scale and glow only, so an "
            "unhighlighted cue has no coloured word — or the phrase did not match any "
            "word, usually a normalization mismatch between the cue text and the phrase."
            + (
                f" {outside} highlight-coloured pixels were found elsewhere in the frame;"
                " that is footage, not text."
                if outside
                else ""
            ),
        }

    scale = width / FORMAT_DIMENSIONS[fmt][0]
    lines = _ink_row_runs(
        ink_mask(array)[band_top:band_bottom].sum(axis=1),
        min_run_ink=NOMINAL_FONT_PX[fmt] * scale,
    )
    if len(lines) != 1:
        return {
            "found": False,
            "line_count": len(lines),
            "reason": f"the cue occupies {len(lines)} lines, and each line is centred "
            "independently, so a word's global index does not determine its horizontal "
            "position — the first word of line 2 is at the right of line 2. Check order "
            "on a single-line cue.",
        }

    denominator = max(1, word_count - 1)
    from_start = highlight_word_index / denominator
    if 0.35 <= from_start <= 0.65:
        return {
            "found": False,
            "reason": f"word {highlight_word_index} of {word_count} is near the middle "
            "of the cue, so it sits near the centre of the line under either direction "
            "and carries no reading-order signal. Highlight a word in the first or last "
            "third.",
        }

    cols = np.where(yellow.sum(axis=0) > 0)[0]
    rows = np.where(yellow.sum(axis=1) > 0)[0]
    centre = (int(cols.min()) + int(cols.max())) / 2

    expected_side = "right" if from_start < 0.5 else "left"
    actual_side = "right" if centre > width / 2 else "left"

    return {
        "found": True,
        "highlight_pixels": int(yellow.sum()),
        "columns": [int(cols.min()), int(cols.max())],
        "rows": [int(rows.min()), int(rows.max())],
        "centre_x": round(centre, 1),
        "expected_side": expected_side,
        "actual_side": actual_side,
        "rtl_order_correct": expected_side == actual_side,
    }


def find_watermark(
    frame: np.ndarray,
    *,
    expected_top_fraction: float,
    reference: np.ndarray | None = None,
    tolerance_fraction: float = 0.05,
) -> dict[str, Any]:
    """Locate the watermark near an expected vertical position.

    ## Why this needs a reference frame

    The watermark cannot be found by appearance. It is white text at 0.6 opacity with a
    soft drop shadow, drawn straight onto the footage with no panel behind it, and at
    that opacity it composites to roughly `0.6·255 + 0.4·footage` — around 153 over dark
    footage and higher over bright. Every discriminator that only looks at the frame was
    measured against real renders and failed:

    * A brightness threshold selects bright footage. Over the brightest clip the search
      band was 35% "watermark".
    * Bright-and-neutral fails: sunlit concrete and overcast sky are both.
    * Local contrast — a bright pixel with a dark one nearby — fails because textured
      footage is nothing but bright pixels with dark ones nearby. Worst false positive
      was 5003 pixels against the real mark's 792.
    * Row-gradient energy fails: at 26:1 peak-to-median, footage detail beat the mark's
      own 21:1.
    * Temporal invariance across frames fails: H.264 re-quantizes the static mark
      differently on every frame, so it is not invariant in the encoded output at all.

    What does work is a **difference against the same render with the watermark
    removed**. Everything else in the composition is deterministic — same footage, same
    frame, same seed — so the diff isolates the mark exactly. Measured on a lossless
    still pair: 2874 pixels differ out of 518400, all of them inside the mark's bounding
    box, and the rest of the frame is bit-identical.

    Pass `reference` as the same frame rendered with `watermark: {persianText: "",
    latinText: ""}`.

    Prefer lossless stills (`remotion still`) over frames pulled from an MP4. On a
    lossless pair the diff is exact: measured rows 148..160 and columns 53..260 against
    a true extent of the same. On an MP4 pair the vertical extent still comes out exact
    — 446..459 — but H.264 scatters small differences into neighbouring columns, and the
    measured horizontal extent widens by tens of pixels (84..375 against a true
    167..372). Enough to confirm presence, position, and that nothing is clipped; not
    enough to measure the mark's width.

    ## Without a reference

    Falls back to an ink threshold, which is only valid on a **footage-free** frame — a
    render with `shots: []`, where the background is the composition's black fill. That
    is a cheap and useful check on its own: it verifies the four phases and the
    migration path in isolation. On a frame that contains footage it will find the
    footage, so the fallback refuses to guess and says which input it needs.
    """
    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape

    centre_row = int(height * expected_top_fraction)
    span = int(height * tolerance_fraction)
    lo, hi = max(0, centre_row - span), min(height, centre_row + span)
    band = array[lo:hi]

    if reference is not None:
        reference_array = np.asarray(reference, dtype=int)
        if reference_array.shape != array.shape:
            raise ValueError(
                f"reference frame is {reference_array.shape} but the frame is "
                f"{array.shape}; both must come from the same composition and scale"
            )
        mask = np.abs(band - reference_array[lo:hi]).max(axis=2) > DIFF_THRESHOLD
        method = "difference"
    else:
        if band.size and float(np.median(band.max(axis=2))) > FOOTAGE_FREE_CEILING:
            return {
                "found": False,
                "method": "ink",
                "searched_rows": [lo, hi],
                "reason": "the search band contains footage, which the ink threshold "
                "cannot tell from the watermark. Pass `reference` — the same frame "
                "rendered with an empty watermark — or render footage-free with "
                "shots: [].",
            }
        mask = band.max(axis=2) > WATERMARK_INK_THRESHOLD
        method = "ink"

    # The mark is one line of type. A per-row density floor keeps the glyph rows and
    # drops the faint halo of shadow difference around them, which extends tens of rows
    # past the glyphs and is contiguous with them. Two floors: an absolute one so a
    # nearly-empty band cannot promote its own noise to a detection, and a relative one
    # because the halo grows with the mark.
    row_counts = mask.sum(axis=1)
    floor = max(
        int(round(MIN_WATERMARK_ROW_FRACTION * width)),
        int(row_counts.max() * MIN_WATERMARK_PEAK_FRACTION),
        6,
    )
    kept = mask & (row_counts >= floor)[:, None]

    if not kept.any():
        return {
            "found": False,
            "method": method,
            "searched_rows": [lo, hi],
            "reason": "no watermark-shaped ink in the expected band — the migration "
            "interpolation may have collapsed, the render may be shorter than the "
            "watermark's four phases, or the expected position may be wrong for this "
            "format",
        }

    rows = np.where(kept.sum(axis=1) > 0)[0]
    cols = np.where(kept.sum(axis=0) > 0)[0]
    return {
        "found": True,
        "method": method,
        "rows": [lo + int(rows.min()), lo + int(rows.max())],
        "columns": [int(cols.min()), int(cols.max())],
        "centre_x": round((int(cols.min()) + int(cols.max())) / 2, 1),
        "ink_pixels": int(kept.sum()),
        "clipped_at_edge": bool(cols.min() <= 1 or cols.max() >= width - 2),
    }

def verify_frames(
    frames: Sequence[tuple[str, np.ndarray]], fmt: PersianFormat = "vertical"
) -> dict[str, Any]:
    """Measure a set of labelled frames and summarize.

    Answers the question the compose stage has: is there any frame where the text
    rendered wrongly? Frames with no text are not failures — sampling between cues is
    legitimate — but a set where *no* frame has text is reported, since that means
    either the sampling or the render is wrong.
    """
    measurements: dict[str, dict[str, Any]] = {}
    problems: list[str] = []

    for label, frame in frames:
        measurement = measure_subtitle_text(frame, fmt)
        measurements[label] = measurement.to_dict()
        problems.extend(f"{label}: {problem}" for problem in measurement.problems)

    with_text = [label for label, data in measurements.items() if data["glyph_pixels"]]
    if frames and not with_text:
        problems.append(
            "no sampled frame contains subtitle text — either every frame was sampled "
            "between cues, or the font failed to load and the text is tofu"
        )

    return {
        "frames": measurements,
        "frames_with_text": with_text,
        "problems": problems,
        "passed": not problems,
    }
