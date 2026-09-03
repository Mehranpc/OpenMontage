"""Frame-level verification for Persian renders.

The compose stage has exactly one check worth doing: did the Persian text actually
render correctly? A completed render proves the props were well-formed and nothing
more. Tofu boxes, reversed reading order, and type that drifted off its anchor all
produce a perfectly valid MP4 of the right duration.

## Why this is harder than it looks

The obvious detector is a brightness threshold:

    ink = frame.max(axis=2) > 200          # "find the bright text"

Over dark footage this works. Over *bright* footage — a sunlit table, an overexposed
sky — it selects the footage, the measured extent becomes the whole frame, and the
check reports text out of place while the text is perfectly placed. It fails precisely
when the footage is most likely to cause a real contrast problem, so the false alarm
hides the true one. This was observed, not hypothesized: eight text frames from a real
render, seven over dark clips, one over a bright one, and the eighth was the only
"failure".

Two attempted fixes also failed, and both are worth recording because they look
sounder than they are:

* **Find the darkened region by its brightness dip.** Comparing row-mean brightness
  inside the text region against the rest of the frame fails when the wash is a
  gradient: the mean over a full row is dominated by whatever the footage is doing
  beside the type, and over a bright clip the dip vanishes into the footage's own
  variation.

* **Per-column darkening ratio.** Compare each column inside the region against the
  same column above it; a covered column should drop by the scrim's alpha. This fails
  on the frames where a camera move means the footage above a column is not what would
  have been under it.

## What actually works

Three facts about the composition, none of which depends on the footage:

1. **The geometry is deterministic.** The moment zone and the anchor column come from
   `tokens.ts`, so where ink may land is computable from the format and the frame's own
   width. No detection needed.

2. **The scrim caps what the footage can present.** `SCRIM.peakAlpha` is 0.72, so
   behind the type even fully clipped white footage composites to at most
   `255·(1−0.72) = 71`. Every ink in the palette has a maximum channel far above that:
   ink 247, secondary 214, accent 255. So `max(channel) > SCRIM_CEILING` separates ink
   from scrimmed footage *structurally* rather than by brightness — and unlike a raw
   brightness threshold it cannot be defeated by a bright clip, because the scrim is
   between the clip and the camera. Measured against the real 66-second render, the
   brightest pixel anywhere in the vertical moment zone composites to exactly 71.4.

3. **A moment shares one right edge with every other moment.** Not a centre — an edge.
   That is a much stronger invariant than "inside the safe area", and it is what
   catches the specific regression this model exists to prevent: type that drifted back
   to centre-aligned still sits inside the width budget, so a width-only check passes
   it, but its right edge is hundreds of pixels off the anchor.

A per-run ink floor removes the few specular pixels that do pass — by *run total*, not
per row: one em of ink per run of rows is scale-correct for both a 540px proof render
and a 1920px landscape frame, where no single width fraction is.

## What the contrast number means here

The scrim guarantees a floor rather than merely improving the odds. Behind the type it
composites 72% black over whatever is there, so the brightest surface it can present is
71.4, and the palette's *weakest* ink on that surface — the accent, `#FFC24B` — measures
5.75:1. That makes `SCRIM_GUARANTEED_CONTRAST` diagnostic rather than advisory: a
reading below it cannot be "the grade is too weak for this footage", because no footage
can produce it through a working scrim. It means the scrim did not render, and the type
is sitting directly on the clip — where the same ink measures 1.09:1.

## What this module does not check

Whether the *right* moments were chosen, or whether their text is well written. Those
are editorial judgements, made at the edit stage against the script. `lib/persian_moments.py`
checks the structural half — pacing, coverage, per-kind limits — before a render exists.

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

#: Rows a moment's ink may occupy, as fractions of frame height.
#:
#: Mirrors `computeMomentZone` in `tokens.ts`, which derives them from the height
#: budget and the optical centre rather than stating them. They are transcribed
#: here — and pinned against the TypeScript source by
#: `tests/contracts/test_persian_geometry_parity.py` — because the verifier must be
#: usable without a Node toolchain.
#:
#: The zone is the envelope of the *tallest legal* moment — the height budget the
#: ladder refuses to exceed (801.8px in vertical, 562.5px in landscape), plus the
#: rule — centred on the optical centre of the usable frame. A real moment is often
#: much shorter, so ink anywhere inside the envelope is legitimate; ink outside it
#: means the layout measured against something other than the vendored font.
#:
#: Grew from the slot-model zone when moments became phrases: a stack of lead +
#: two-line hero + tail is taller than a numeral with satellites. The growth moved
#: the watermark's quiet position up with it, through the shared derivation in
#: `computeWatermarkQuietTopPct` — which is exactly why both are derived and pinned
#: in one place rather than restated as literals.
MOMENT_ZONE_FRACTION: dict[str, dict[str, float]] = {
    "vertical": {"top": 0.230419, "bottom": 0.649581},
    "landscape": {"top": 0.238211, "bottom": 0.761789},
}

#: The anchor column and the left bound of the text column, in px at nominal width.
#: Mirrors `computeMomentColumns`. Both scale with the frame.
#:
#: `left` bounds the *authorised line budget* — the width `computeLineBudgetPx`
#: allows before the per-span paint drift margin is charged. Because Chromium
#: paints an `inline-block` word span ~2% wider than the canvas advance of the
#: same word (measured at +17px..+32px on 903px lines), a line that fills its
#: budget can still paint a little past `left`. The fitter's margin
#: (`FIT_SPAN_DRIFT_FRACTION`) exists so that this paint still lands inside
#: `left` plus the overshoot tolerance below; a line blowing through *that* is a
#: fitter bug, not paint drift.
MOMENT_COLUMNS_PX: dict[str, dict[str, float]] = {
    "vertical": {"left": 113.08, "right": 993.6},
    "landscape": {"left": 197.92, "right": 1766.4},
}

#: How far a line's rightmost ink may fall short of the anchor, in px at nominal width.
#:
#: Not zero, and the reason is typographic rather than a tolerance for sloppiness: the
#: anchor is the edge of the glyph's *advance box*, and every glyph has a right side
#: bearing — blank space inside its own box. Measured across the production script's
#: real lines in the vendored Estedad at their painted sizes, the worst case is 20px, on
#: the Persian numeral «۲۲۶۴» at the 216px lifted hero of the coffee render (the
#: largest hero the current ladder plus the presence lift produces). Ordinary Persian
#: text sits at 2-5px.
#:
#: 32 leaves margin over the measured worst case without being loose enough to accept a
#: real misalignment: centred text in vertical would miss the anchor by 45px on the
#: *narrowest* real line and by hundreds on a short one.
ANCHOR_TOLERANCE_PX = 32

#: Where the watermark sits in each phase, as a fraction of frame height. Mirrors
#: `WATERMARK_RESTING_TOP_PCT` and `computeWatermarkQuietTopPct` in `tokens.ts`; both
#: are pinned against the TypeScript source by
#: `tests/contracts/test_persian_geometry_parity.py`.
#:
#: Both positions are above the moment zone in both formats, which is what lets the
#: watermark search band be narrow enough to be meaningful.
#:
#: The quiet position moved *up* from 0.2445 when the moment zone grew: it is
#: derived as `max(resting, zone.top − clearance)`, so the mark clears the taller
#: envelope by the same clearance it always had. That movement is why the value is
#: derived and pinned rather than a literal — a literal would still be sitting
#: inside the new zone's top rows.
WATERMARK_TOP_FRACTION: dict[str, dict[str, float]] = {
    "vertical": {"quiet": 0.170419, "resting": 0.11},
    "landscape": {"quiet": 0.178211, "resting": 0.08},
}

#: Brightest channel value the scrim can present, plus margin for H.264 ringing.
#:
#: The arithmetic: `SCRIM.peakAlpha` is 0.72, so clipped white footage composites to
#: `255·0.28 = 71.4` behind the type. Measured on the real 66-second render, the
#: brightest pixel anywhere in the vertical moment zone is exactly 71.4 — the cap is
#: reached in practice, so a ceiling at the cap would sit on the boundary.
#:
#: 95 puts the threshold 24 above the physical cap and 147 below the weakest ink's
#: maximum channel (secondary, 214), so both sides have room. Used on the *maximum*
#: channel because the accent is strongly chromatic: `#FFC24B` has a blue channel of
#: 75, so any test on the minimum channel would reject the accent as footage.
SCRIM_CEILING = 95

#: Contrast the scrim guarantees against any footage whatsoever.
#:
#: 72% black over clipped white presents 71.4, and the palette's weakest ink on that
#: surface is the accent at 5.75:1. Rounded down to 5.6 for encoder noise.
#:
#: A reading below this is not "the grade is too weak" — no footage can produce it
#: through a working scrim. It means the scrim did not render and the type is on the
#: bare clip, where the same ink measures 1.09:1.
SCRIM_GUARANTEED_CONTRAST = 5.6

#: Fraction of the moment zone that may be ink before the reading is rejected as a
#: detection failure rather than reported as a measurement.
#:
#: The mask is not a brightness threshold — it is "brighter than the scrim can present"
#: — so if the scrim fails to render, *every* pixel of bright footage passes and the
#: zone comes back 100% ink. That produces a confidently wrong measurement: full-width
#: extents, a fabricated line count, and a contrast ratio of `None` because the
#: background sample is empty.
#:
#: Measured on synthetic frames set in the real font at the real sizes, the densest
#: legitimate moment — a figure with a two-line lead/tail and a source line — fills
#: 9.6% of the zone, and a three-line statement fills 6.9%. 35% is far above every
#: real case and far below the 100% a missing scrim produces, so the two cannot be
#: confused.
ZONE_INK_CEILING = 0.35

#: Gap between two role blocks, as a fraction of the size it is derived from.
#: Mirrors `STACK_GAP_RATIO` in `remotion-composer/src/persian/tokens.ts` and is
#: pinned against it by `tests/contracts/test_persian_geometry_parity.py`.
STACK_GAP_RATIO = 0.55

#: Pixels of antialiased rim around accent glyphs, excluded when isolating neutral ink.
#:
#: An accent glyph's edge blends toward the scrim, so those pixels are bright enough to
#: be ink but too far from `#FFC24B` to be accent. 3px covers the rim at every painted
#: size, measured on the 216px lifted hero of the coffee render where it is widest.
ACCENT_FRINGE_PX = 3

#: Row gap, in pixels, that separates two lines of text.
LINE_GAP_PX = 4

#: How far ink may spill *past* the text column's edges before it counts as overflow.
#:
#: Not the same quantity as `ANCHOR_TOLERANCE_PX`, which measures ink falling *short* of
#: the anchor and is sized to the glyph's right side bearing. This one measures ink going
#: the other way, and its causes are the renderer's rather than the font's: glyph
#: antialiasing writes partial pixels outside the advance box, and H.264 ringing adds a
#: little more around a high-contrast edge.
#
# Two components, because the paint has two. The flat part is antialiasing and encoder
# ringing, which do not scale with type: 8px, measured on the real render as the cap of
# 1.4-4.4px spills carrying 8-30 pixels. The proportional part is glyph *ink overhang*
# past the advance box — Chromium paints an initial «آ» 0.065em past where canvas
# `measureText` says its advance ends (measured +14px on the 216px hero of the real
# coffee render; node-canvas's `measureInk` sees none of it, the same DOM-vs-canvas
# divergence the ZWNJ charge covers on the width axis). The old 8px constant was
# measured at caption-era 80px type, where the proportional part is ~5px and the flat
# part hid it; at the new 216px hero it is 14px and the constant failed a correct frame.
#: The tolerance per line is therefore `max(INK_OVERSHOOT_PX, INK_OVERSHOOT_EM ×
#: the line's own measured ink height)` — the run height is a stand-in for the painted
#: em, available without knowing the fitted size.
#: The per-line allowance is the flat part **plus** the proportional part — they are
#: independent additive costs, the same shape as `FIT_SAFETY_PX` + the drift fraction
#: in the fitter's budget. The measured worst case on the real render is a 216px hero
#: whose initial «آ» paints ~11px of solid overhang with ~4px of antialiasing spray
#: beyond it: 8 + 0.065 × 235px-run ≈ 23px covers both with margin, while a genuine
#: column break — ink running to the frame edge, 86px away — still fails loudly.
INK_OVERSHOOT_PX = 8
INK_OVERSHOOT_EM = 0.065

#: Smallest type each format paints, from `TYPOGRAPHY.sourcePx`. A run of ink rows must
#: carry at least this many ink pixels in total to count as a line: one em of ink is
#: less than a single Persian letter, so no real line falls below it, while a specular
#: highlight surviving the scrim — a handful of pixels — does.
#:
#: The *smallest* size rather than a nominal one, because a source line is real text
#: that must be found; sizing the floor to the statement size would discard it.
MIN_LINE_PX = {"vertical": 30, "landscape": 26}

#: Margin beyond the ink that the scrim plateau extends, px. Mirrors
#: `SCRIM_PLATEAU_MARGIN_PX` in `remotion-composer/src/persian/tokens.ts` and
#: `PersianMomentBlock.tsx:scrimStops()` — the plateau must cover every row the
#: moment's ink occupies plus this margin, because `peakAlpha` is the only alpha
#: the contrast floor was computed against. Pinned by
#: `tests/contracts/test_persian_geometry_parity.py`.
SCRIM_PLATEAU_MARGIN_PX = 28

#: Accent pixels, as a fraction of the moment zone, that mean a figure or term is
#: painting. Used only to check that a *gap* frame is empty of type.
#:
#: The accent is the one ink findable without a scrim behind it, because its channel
#: spread of 180 is a property of the colour rather than of the contrast: `accent_mask`
#: admits 0.0000% of real footage pixels. That matters here because a gap frame has no
#: scrim by design, so every brightness-based test sees raw footage and cannot be used.
#:
#: Measured across nine real gap frames and thirteen real moment frames: gaps carry
#: 0.0000-0.0246% accent, and moments with a figure or a term carry 3.84-7.93%. 0.5%
#: sits 20x above the noisiest gap and 7x below the faintest real hero.
#:
#: Every moment paints its hero in the accent (ROLE_COLOR.hero), so this detects an
#: overrun of any kind spilling accent ink into the gap. Measuring the band on
#: figure and term frames is what calibrated the ceiling — those were the frames
#: with measured accent coverage — but the instrument is the hero colour, which
#: statements and hooks paint too.
GAP_ACCENT_CEILING = 0.005



def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Grow a boolean mask by `radius` pixels in every direction, including diagonals.

    Written with shifted ORs rather than a library call because `scipy` is not a
    dependency of this repo and pulling one in for a small morphological op would be the
    larger cost. Radius is a few px, so the loop is cheap.

    **Each pass reads the accumulating mask, not the original**, and that is the whole
    difference between this and the version it replaces. Shifting the original four ways
    grows a *cross*: a pixel diagonally adjacent to ink is never covered, at any radius.
    Verified — at radius 5 the old form still left `(6,6)` unset for ink at `(5,5)`.

    A cross is not merely a smaller square. An accent glyph's antialiased rim follows the
    glyph's outline, so on any diagonal or curved stroke the rim sits diagonally from the
    ink it belongs to, and a cross leaves exactly that rim behind. Those leftover pixels
    are bright enough to pass `ink_mask` but too far from `#FFC24B` to pass
    `accent_mask`, so they land in the neutral mask and are read as a separate element.

    That is not hypothetical. On the real 66-second render it put 43 stray neutral pixels
    up to column 993 on the hero's own rows — every one of them within 4px of accent ink,
    the rim of «۲۲۶۴» — and `check_moment_arrangement` read them as the unit sitting to
    the right of the hero. It reported a reversed RTL row on a frame that was correct,
    which is the worst failure a verifier has: it accuses the thing it was built to
    protect. Two passes per axis over the growing mask make the structuring element the
    square it was documented to be, and the leak disappears (923 max column at radius 3,
    with the real unit at 380-421 carrying 553 of the 656 remaining pixels).
    """
    grown = mask.copy()
    for _ in range(radius):
        grown[1:, :] |= grown[:-1, :]
        grown[:-1, :] |= grown[1:, :]
    for _ in range(radius):
        grown[:, 1:] |= grown[:, :-1]
        grown[:, :-1] |= grown[:, 1:]
    return grown


def ink_mask(frame: np.ndarray) -> np.ndarray:
    """Pixels bright enough to be type rather than scrimmed footage.

    Tested on the **maximum** channel, which is the opposite of what the predecessor
    did and worth explaining, because the change looks like a loosening.

    The old test was `min(channel) >= 225`: near-white *and* neutral. Neutrality was
    doing the discriminating work, since footage highlights are rarely neutral at that
    level. It had to work that way because the caption panel let bright footage through
    at up to 149, well inside the range real text occupies.

    That reasoning does not survive the new palette. The accent `#FFC24B` has a blue
    channel of 75, so a minimum-channel test rejects the ink that carries every figure
    and every term — the most important type in the video.

    What replaces it is a bound the scrim supplies: behind the type nothing from the
    footage can exceed `255·(1−0.72) = 71.4`, measured and confirmed at exactly that on
    the real render. So a maximum channel above `SCRIM_CEILING` is type, whatever its
    hue, and the discrimination no longer depends on the footage being un-neutral.
    """
    array = np.asarray(frame, dtype=int)
    return array.max(axis=2) > SCRIM_CEILING


def accent_mask(frame: np.ndarray, tolerance: int = 34) -> np.ndarray:
    """Pixels matching the accent `#FFC24B` — a moment's hero, of any kind.

    Separable by colour where the two neutral inks are not, because the accent is
    strongly chromatic: its channel spread is 180, against 5 for `ink` and 16 for
    `inkSecondary`. At an L-infinity tolerance of 34 the nearest neutral ink is 123
    away, so the three never collide — which is exactly why the hero can be located this
    way and the supporting lines cannot.

    ## Only meaningful inside the moment zone

    Warm footage — a sunset, a tungsten interior — genuinely does fall within 34 of the
    accent, and this function will match it. That is not a defect, because the accent is
    never looked for outside the scrim: under `SCRIM.peakAlpha` the footage cannot
    exceed 71 in any channel, and the accent's red is 255, so inside the zone the
    separation is 184 rather than 34. `check_moment_arrangement` slices the zone before
    calling this, and nothing else should call it without doing the same.

    The tolerance is therefore sized for encoder noise and antialiasing, not for
    rejecting footage — the scrim already did that.
    """
    array = np.asarray(frame, dtype=int)
    target = np.array([255, 194, 75])
    return np.abs(array - target).max(axis=2) <= tolerance


def moment_zone(
    frame_width: int, frame_height: int, fmt: PersianFormat
) -> tuple[int, int]:
    """Rows a moment's ink may occupy, computed from the tokens.

    Scales with the frame, so a `--scale=0.5` proof render measures correctly: the zone
    is expressed as fractions of height, so no explicit scaling is needed — which is
    itself the reason the tokens express it that way.
    """
    zone = MOMENT_ZONE_FRACTION[fmt]
    top = int(round(zone["top"] * frame_height))
    bottom = int(round(zone["bottom"] * frame_height))
    return max(0, top), min(frame_height, bottom)


def moment_centre_fraction(fmt: PersianFormat) -> float:
    """Optical centre of the moment zone, as a fraction of height. Mirrors
    `computeMomentCentreFraction` in `tokens.ts`. Present so `scrim_plateau`
    can derive from the same tokens the render uses."""
    zone = MOMENT_ZONE_FRACTION[fmt]
    return (zone["top"] + zone["bottom"]) / 2


def scrim_plateau(
    frame_width: int, frame_height: int, fmt: PersianFormat, stack_height_px: float
) -> tuple[int, int]:
    """Rows the scrim actually darkens at peak alpha for this moment.

    Mirrors `computeScrimPlateau` in `tokens.ts` / `scrimStops` in
    `PersianMomentBlock.tsx`: half the fitted stack plus the plateau margin,
    centred on the optical centre, scaled with the frame. The verifier must
    measure only rows the scrim guarantees — `SCRIM_CEILING` holds only inside
    this band — so every ink-bearing check is scoped here, not to the zone
    envelope.
    """
    centre_frac = moment_centre_fraction(fmt)
    centre_px = centre_frac * frame_height
    scale = frame_width / FORMAT_DIMENSIONS[fmt][0]
    # `stack_height_px` is the fitted height at nominal width; scale with the frame
    half_px = (stack_height_px * scale) / 2 + SCRIM_PLATEAU_MARGIN_PX * scale
    top = int(round(centre_px - half_px))
    bottom = int(round(centre_px + half_px))
    return max(0, top), min(frame_height, bottom)


def moment_columns(frame_width: int, fmt: PersianFormat) -> tuple[float, float]:
    """The left bound and the anchor column, in px, scaled to this frame."""
    scale = frame_width / FORMAT_DIMENSIONS[fmt][0]
    columns = MOMENT_COLUMNS_PX[fmt]
    return columns["left"] * scale, columns["right"] * scale


def _ink_row_runs(
    row_counts: np.ndarray, *, min_run_ink: int
) -> list[tuple[int, int]]:
    """Group ink rows into lines, discarding runs too faint to be text.

    Filtering by *run total* rather than per-row density is what makes this robust
    across scales. A per-row floor has to be expressed as a fraction of frame width,
    and no single fraction works for both a 540px proof render and a 1920px landscape
    frame: the value that passes a short line at 540px also passes a specular highlight
    at 1920px.

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
    these terms, and because a channel mean rates the warm accent as dimmer than it
    reads — which would flag a correct design as low contrast.
    """
    channels = np.asarray(frame, dtype=float) / 255.0
    linear = np.where(
        channels <= 0.03928, channels / 12.92, ((channels + 0.055) / 1.055) ** 2.4
    )
    return 0.2126 * linear[..., 0] + 0.7152 * linear[..., 1] + 0.0722 * linear[..., 2]


@dataclass
class MomentMeasurement:
    """What was found in one frame's scrim plateau."""

    zone_rows: tuple[int, int]
    plateau_rows: tuple[int, int] | None
    glyph_rows: tuple[int, int] | None
    glyph_columns: tuple[int, int] | None
    glyph_pixels: int
    line_count: int
    #: Distance from each line's rightmost ink to the anchor column, px. One entry per
    #: line, so a single stray line is visible rather than averaged away.
    anchor_offsets_px: list[float] = field(default_factory=list)
    inside_text_column: bool | None = None
    contrast_ratio: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return self.glyph_pixels > 0

    @property
    def worst_anchor_offset_px(self) -> float | None:
        return max(self.anchor_offsets_px) if self.anchor_offsets_px else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_rows": list(self.zone_rows),
            "plateau_rows": list(self.plateau_rows) if self.plateau_rows else None,
            "glyph_rows": list(self.glyph_rows) if self.glyph_rows else None,
            "glyph_columns": list(self.glyph_columns) if self.glyph_columns else None,
            "glyph_pixels": self.glyph_pixels,
            "line_count": self.line_count,
            "anchor_offsets_px": [round(v, 1) for v in self.anchor_offsets_px],
            "worst_anchor_offset_px": (
                round(self.worst_anchor_offset_px, 1)
                if self.worst_anchor_offset_px is not None
                else None
            ),
            "inside_text_column": self.inside_text_column,
            "contrast_ratio": self.contrast_ratio,
            "problems": list(self.problems),
        }


def measure_moment(
    frame: np.ndarray,
    fmt: PersianFormat = "vertical",
    *,
    plateau_rows: tuple[int, int] | None = None,
    stack_height_px: float | None = None,
) -> MomentMeasurement:
    """Measure the typographic moment in one frame.

    Reports rather than asserts. A frame sampled mid-entrance legitimately has partial
    opacity, and a frame in the gap between moments legitimately has no text at all —
    that gap is the point of the model, and it covers nearly half the runtime. Only the
    caller knows which frames it chose and what each should contain.

    `problems` carries the faults that are unambiguous whatever the frame's timing:
    ink outside the text column, a line that missed the anchor, and contrast below the
    floor the scrim guarantees.

    The measurement is scoped to the scrim plateau — the rows the scrim actually
    darkens at peak alpha — not the zone envelope. The zone is the envelope of
    the tallest legal moment; the plateau is this moment's own darkened band
    (``stackHeightPx/2 + SCRIM_PLATEAU_MARGIN_PX`` around the optical centre).
    ``ink_mask`` and ``SCRIM_CEILING`` hold only inside that band; outside it
    bright footage passes, so measuring over the whole zone misreads footage as
    type. Pass either ``plateau_rows`` or ``stack_height_px`` (the fitted
    ``heightPx``); if neither is given the zone is used for backward
    compatibility — but that legacy path is deprecated for moment frames.
    """
    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape
    zone_top, zone_bottom = moment_zone(width, height, fmt)
    left_bound, anchor = moment_columns(width, fmt)

    if plateau_rows is not None:
        plateau_top, plateau_bottom = plateau_rows
    elif stack_height_px is not None:
        plateau_top, plateau_bottom = scrim_plateau(width, height, fmt, stack_height_px)
    else:
        plateau_top, plateau_bottom = zone_top, zone_bottom

    # Clamp plateau inside the frame; also compute the mask over the plateau only.
    # The ink ceiling, line grouping and extent checks all assume the scrim
    # caps the background — true only on the plateau.
    plateau_top = max(0, min(height, plateau_top))
    plateau_bottom = max(0, min(height, plateau_bottom))
    if plateau_bottom <= plateau_top:
        plateau_top, plateau_bottom = zone_top, zone_bottom

    mask = ink_mask(array)[plateau_top:plateau_bottom]
    scale = width / FORMAT_DIMENSIONS[fmt][0]

    # Reject the frame before measuring it if the mask is implausibly full. Every
    # measurement below assumes the mask is type; when the scrim is missing the mask is
    # the footage, and the numbers that come out are precise and meaningless.
    fill = float(mask.mean()) if mask.size else 0.0
    if fill > ZONE_INK_CEILING:
        return MomentMeasurement(
            zone_rows=(zone_top, zone_bottom),
            plateau_rows=(plateau_top, plateau_bottom),
            glyph_rows=None,
            glyph_columns=None,
            glyph_pixels=int(mask.sum()),
            line_count=0,
            problems=[
                f"{fill:.0%} of the plateau is above the scrim ceiling, against "
                f"{ZONE_INK_CEILING:.0%} allowed and under 10% for the densest real "
                "moment. The scrim did not render, so the footage itself is passing the "
                "ink test and no geometric measurement of this frame means anything. "
                "Fix the scrim before reading any other number."
            ],
        )

    lines = _ink_row_runs(
        mask.sum(axis=1), min_run_ink=max(4, int(round(MIN_LINE_PX[fmt] * scale)))
    )

    if not lines:
        return MomentMeasurement(
            zone_rows=(zone_top, zone_bottom),
            plateau_rows=(plateau_top, plateau_bottom),
            glyph_rows=None,
            glyph_columns=None,
            glyph_pixels=0,
            line_count=0,
        )

    text_mask = np.zeros_like(mask)
    for lo, hi in lines:
        text_mask[lo : hi + 1] = mask[lo : hi + 1]

    cols = np.where(text_mask.sum(axis=0) > 0)[0]
    glyph_top = plateau_top + lines[0][0]
    glyph_bottom = plateau_top + lines[-1][1]

    # Per line, because the anchor is a property of each line, not of the block. A
    # block-level maximum would be satisfied by one correct line beside several that
    # drifted — which is precisely the shape of a flex-alignment regression.
    #
    # `offsets` stays the raw short-of-anchor distance (positive = short), so the
    # anchor check reads the same quantity it always did. The overhang allowance is
    # applied per line separately, scaled by that line's own run height (see
    # `INK_OVERSHOOT_EM`): the overhang is a property of the glyph, and a 216px hero
    # overhangs proportionally where an 82px lead does not.
    offsets = [
        float(anchor - int(np.where(text_mask[lo : hi + 1].sum(axis=0) > 0)[0].max()))
        for lo, hi in lines
    ]

    line_allowances = [
        (INK_OVERSHOOT_PX + INK_OVERSHOOT_EM * float(hi - lo + 1)) * scale
        for lo, hi in lines
    ]
    max_allowance = max(line_allowances)
    inside = bool(
        cols.min() >= left_bound - max_allowance
        and cols.max() <= anchor + max_allowance
    )
    ratio = _measure_contrast(array, text_mask, plateau_top, cols)

    tolerance = ANCHOR_TOLERANCE_PX * scale
    problems: list[str] = []
    if not inside:
        problems.append(
            f"ink spans x {int(cols.min())}..{int(cols.max())} but the text column is "
            f"{left_bound:.0f}..{anchor:.0f} (±{max_allowance:.0f}px, scaled per line for "
            "antialiasing and glyph overhang) — the layout measured against a different "
            "font than the one that painted, or the column tokens changed"
        )
    stray = [(index, value) for index, value in enumerate(offsets) if value > tolerance]
    if stray:
        worst = max(value for _, value in stray)
        problems.append(
            f"{len(stray)} of {len(lines)} lines miss the right anchor, worst by "
            f"{worst:.0f}px against a {tolerance:.0f}px tolerance. Every line of every "
            "moment shares one right edge; a line short of it means the flex row "
            "centred or left-aligned instead of anchoring."
        )
    overruns = [
        (index, -value, line_allowances[index])
        for index, value in enumerate(offsets)
        if value < -line_allowances[index]
    ]
    if overruns:
        worst_overrun = max(value for _, value, _ in overruns)
        problems.append(
            f"ink extends {worst_overrun:.0f}px past the anchor column, beyond the "
            f"{max_allowance:.0f}px allowance for its own line height — the type is "
            "overflowing its column toward the frame edge"
        )
    if ratio is not None and ratio < SCRIM_GUARANTEED_CONTRAST:
        problems.append(
            f"contrast {ratio:.2f}:1 is below the {SCRIM_GUARANTEED_CONTRAST}:1 the "
            "scrim guarantees against any footage — the scrim did not render, so the "
            "type is sitting directly on the clip"
        )

    return MomentMeasurement(
        zone_rows=(zone_top, zone_bottom),
        plateau_rows=(plateau_top, plateau_bottom),
        glyph_rows=(glyph_top, glyph_bottom),
        glyph_columns=(int(cols.min()), int(cols.max())),
        glyph_pixels=int(text_mask.sum()),
        line_count=len(lines),
        anchor_offsets_px=offsets,
        inside_text_column=inside,
        contrast_ratio=round(ratio, 2) if ratio is not None else None,
        problems=problems,
    )


def _measure_contrast(
    array: np.ndarray,
    mask: np.ndarray,
    zone_top: int,
    cols: np.ndarray,
) -> float | None:
    """Contrast between the glyphs and the surface immediately around them.

    Sampling locally rather than from a fixed strip is required by the scrim being a
    gradient. The predecessor sampled a panel's bottom padding, which worked because a
    panel has one flat surface; here the alpha varies by row, so the only honest
    background for a line is what is beside that line.

    The sample is a *ring* around the ink's bounding box rather than the gaps inside it,
    and that is not a stylistic choice. Interstitial gaps vanish in two ordinary cases:
    a solid rule, and heavy display type at 260px where the counters are a small
    fraction of the box. Sampling only inside returns `None` for both — a missing
    measurement that reads as "could not check" when the truth is "no gaps to look
    through". The ring always exists.

    The ink is excluded with a 3px dilation. Antialiased edges are a blend of ink and
    background, so leaving them in pulls the background sample toward the ink and
    inflates the ratio — the direction that hides a fault.
    """
    luminance = relative_luminance(array)

    rows = np.where(mask.sum(axis=1) > 0)[0]
    if rows.size == 0:
        return None
    top, bottom = int(rows.min()), int(rows.max()) + 1
    left, right = int(cols.min()), int(cols.max()) + 1

    # Ring width scales with the type: a 30px source line wants a few px, a 216px hero
    # wants tens, and a fixed value is wrong for one of them. Clipped to the mask, so a
    # moment filling its zone simply gets a narrower ring rather than an index error.
    pad = max(4, int(round(0.3 * (bottom - top))))
    zone_height, zone_width = mask.shape
    outer_top, outer_bottom = max(0, top - pad), min(zone_height, bottom + pad)
    outer_left, outer_right = max(0, left - pad), min(zone_width, right + pad)

    window = mask[outer_top:outer_bottom, outer_left:outer_right]
    zone_luminance = luminance[
        zone_top + outer_top : zone_top + outer_bottom, outer_left:outer_right
    ]

    glyph_values = zone_luminance[window]
    background_values = zone_luminance[~_dilate(window, 3)]
    if glyph_values.size == 0 or background_values.size == 0:
        return None

    text_l = float(glyph_values.mean())
    background_l = float(np.median(background_values))
    return (max(text_l, background_l) + 0.05) / (min(text_l, background_l) + 0.05)


def _resolve_plateau(
    frame_width: int,
    frame_height: int,
    fmt: PersianFormat,
    plateau_rows: tuple[int, int] | None,
    stack_height_px: float | None,
) -> tuple[int, int]:
    if plateau_rows is not None:
        top, bottom = plateau_rows
        return max(0, min(frame_height, top)), max(0, min(frame_height, bottom))
    if stack_height_px is not None:
        return scrim_plateau(frame_width, frame_height, fmt, stack_height_px)
    z_top, z_bottom = moment_zone(frame_width, frame_height, fmt)
    return z_top, z_bottom


def check_moment_arrangement(
    frame: np.ndarray,
    *,
    roles: Sequence[str],
    fmt: PersianFormat = "vertical",
    plateau_rows: tuple[int, int] | None = None,
    stack_height_px: float | None = None,
    flat_accent: bool = False,
) -> dict[str, Any]:
    """Verify a moment's segment order from pixel geometry.

    ## What it checks

    The segment array is the reading order of one Persian phrase, painted top to
    bottom exactly as authored — «مطالعهٔ دانشگاه اولوی فنلاند روی» above «۲۲۶۴
    نفر», never rearranged. This check reads that back off the frame:

    * **The accent hero sits below every neutral segment authored before it** (the
      `lead`s) **and above every neutral segment authored after it** (the `tail`s
      and the `source`). A stack that sorted by role, or that inverted the phrase
      to put the fact above its frame, fails here without any planted marker or
      expected image.
    * **No neutral ink sits above the hero when nothing was authored above it** —
      the check that catches the satellite residue the slot model painted («نفر»
      floating at the numeral's baseline, a label below a kicker the eye read as a
      second object), because under the segment model there is no legal way to
      produce ink above a first-position hero.

    The hero is located by colour, which is reliable here and nowhere else: the
    accent is the only strongly chromatic ink in the palette, and it admits no
    footage pixels at all (see `accent_mask`). Every moment carries exactly one
    hero in the accent, so this check applies to statements too — an improvement
    on the predecessor, which could not check statements at all because under the
    slot model only figures and terms had accent heroes.

    ## Build steps

    A built moment dims its earlier steps to 0.55 opacity rather than removing
    them. Dimmed accent ink at 55% over the 0.72 scrim composites to roughly
    (0.55·255 + 0.45·71) ≈ 173-100 channel spread — closer to the accent than to
    any neutral ink, but no longer inside `accent_mask`'s tolerance. So on a frame
    after the second step this check sees the *active* hero (the newest step's)
    and, above it, the dimmed previous step's neutral ink: which is exactly the
    authored order, with the previous step's hero no longer separable by colour.
    The order check therefore still passes on a correct build, and the "ink above
    the hero" it sees is accounted for by the authored roles of the earlier step —
    callers auditing a mid-build frame should pass the roles of the *whole*
    moment, not just the active step.

    ## What it cannot check

    Glyph order *within* a word. A string reversed character by character — the
    classic bad "RTL fix" — produces ink of nearly the same extent, and no pixel
    measurement separates it from correct text without shaping the expected string
    against the same font and correlating profiles. That was tried: on the real
    render the true profile beat its mirror by 0.05-0.07 correlation, against a
    0.86 margin in a clean PIL rendering. H.264 and antialiasing eat the signal,
    so the method reports a confident answer from noise. It is not implemented
    rather than implemented unreliably — a reading-order check that certifies the
    fault it exists to catch is worse than none.

    Intra-word order is instead covered where it can be: `tests/contracts/
    test_persian_text_parity.py` pins the normalization, and the composition sets
    each word as its own span with `unicodeBidi: "embed"`, so ordering is the
    browser's bidi implementation rather than this codebase's arithmetic.

    ## Flat-hook moments

    A flat-hook moment (`flat_accent=True`) paints one block at one size with the
    accent inline on one or two words. There is no accent *block* whose rows can
    sit above or below a neutral block — accent and neutral share every row — so
    the block-order geometry this check asserts does not exist to verify. The
    check reports passed with `flat_accent: True` rather than failing a correct
    frame; ink, anchor, column, and contrast are still measured by
    `verify_frames`, which needs no such carve-out.
    """
    if flat_accent:
        return {
            "checked": True,
            "flat_accent": True,
            "problems": [],
            "passed": True,
            "note": "flat-hook moment: the accent is inline on one or two "
            "words of a single block, so there is no accent block whose rows "
            "could sit above or below a neutral block. Arrangement is N/A by "
            "construction, not unverified by omission.",
        }
    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape
    zone_top, zone_bottom = moment_zone(width, height, fmt)
    plateau_top, plateau_bottom = _resolve_plateau(
        width, height, fmt, plateau_rows, stack_height_px
    )

    if "hero" not in roles:
        return {
            "checked": False,
            "reason": "the authored roles contain no hero; every moment carries "
            "exactly one, so a frame claiming to show a moment without one is a "
            "props-assembly fault.",
        }

    plateau = slice(plateau_top, plateau_bottom)
    accent_all = accent_mask(array)[plateau]

    # The hairline rule above every moment is accent-coloured (3px tall, a solid
    # rectangle), and so is the hero. Without separating them the rule is read as
    # the hero, everything the type paints lands "below the hero", and every
    # correctly ordered stack reports its lead as missing — this exact failure,
    # hit on the first real frame the check ever ran against.
    #
    # The discriminator is height: a rule is a handful of pixels tall and wide as
    # the hero itself, while a hero at even the bottom rung is dozens of pixels of
    # glyph. Runs this short are the rule; anything taller is the hero. The
    # threshold scales with the frame so a 0.5× proof render still separates them.
    scale = width / FORMAT_DIMENSIONS[fmt][0]
    accent = accent_all.copy()
    for lo, hi in _ink_row_runs(accent_all.sum(axis=1), min_run_ink=1):
        if (hi - lo + 1) <= max(6, int(round(6 * scale))):
            accent[lo : hi + 1] = False

    # The accent's *dilated* mask is subtracted, not the mask itself, and that
    # detail is load-bearing. An accent glyph's antialiased rim is a blend of
    # `#FFC24B` and the scrim, so it fails the colour tolerance while still
    # passing the ink test — it lands in `neutral`. Left in, the hero's own
    # outline is read as a lead beside it, and a correctly ordered stack reports
    # ink above the hero. The rule's rim joins the subtraction for the same
    # reason: its antialiased edges are neutral-passing pixels too. Which is to
    # say: this exact bug made the check fail on a correct frame the first time
    # it ran.
    neutral = ink_mask(array)[plateau] & ~_dilate(accent_all, ACCENT_FRINGE_PX)

    if not accent.any():
        return {
            "checked": False,
            "reason": "no accent ink in the moment zone. Either this frame is "
            "between moments, or the moment painted its hero in the wrong colour — "
            "the hero is always the accent, in every kind.",
        }

    accent_rows = np.where(accent.sum(axis=1) > 0)[0]
    hero_top, hero_bottom = int(accent_rows.min()), int(accent_rows.max())
    hero_is_first = roles[0] == "hero"

    result: dict[str, Any] = {
        "checked": True,
        "hero_rows": [plateau_top + hero_top, plateau_top + hero_bottom],
        "problems": [],
    }

    # Neutral ink strictly above the hero's rows, and strictly below.
    above = neutral[:hero_top]
    below = neutral[hero_bottom + 1 :]
    has_above = bool(above.any())
    has_below = bool(below.any())
    result["ink_above_hero"] = has_above
    result["ink_below_hero"] = has_below

    # Segment roles authored before the hero are painted above it; after, below.
    # The build case does not reposition anything — earlier steps stay where they
    # arrived — so band membership follows the authored order for every step.
    hero_index = roles.index("hero")
    expect_above = any(role != "hero" for role in roles[:hero_index])
    expect_below = any(role != "hero" for role in roles[hero_index + 1 :])

    if expect_above and not has_above:
        result["problems"].append(
            "the moment has segments authored before the hero, but no neutral ink "
            "sits above the hero's rows — the lead(s) did not paint, or the stack "
            "sorted the hero to the top. The array order is the reading order; "
            "«مطالعهٔ دانشگاه اولوی فنلاند روی» belongs above «۲۲۶۴ نفر»."
        )
    if not expect_above and has_above:
        result["problems"].append(
            "neutral ink sits above the hero but no segment was authored above it "
            "— residue of a stack that is not the segment model (a unit row, a "
            "kicker, a satellite). Under the segment model there is no legal way "
            "to produce this."
        )
    if expect_below and not has_below:
        result["problems"].append(
            "the moment has segments authored after the hero, but no neutral ink "
            "sits below the hero's rows — the tail(s) or source did not paint, or "
            "the stack order inverted."
        )

    result["passed"] = not result["problems"]
    return result



def expected_stack_gap_px(
    lead_px: float,
    *,
    tail_px: float | None = None,
    claim_qualifier: bool = False,
    scale: float = 1.0,
) -> float:
    """The designed inter-block gap for a moment, mirroring `stackGapPxForMoment`.

    An ordinary moment's gap follows the lead (`computeStackGapPx`). A
    claim+qualifier hook's gap follows the *qualifier* instead: the gap sits
    between the claim and the qualifier, and at 68 × 0.55 = 37px it is the gap
    the approved frame was measured at, while the lead derivation gives
    36 × 0.55 = 20px — a denser stack the approval never saw. The ratio is the
    same `STACK_GAP_RATIO` the whole video uses; only the size it applies to is
    hook-scoped.

    `tail_px` is the fitted qualifier size (`FittedSegment.fontSizePx` of the
    tail role), not a re-derivation of `HOOK_TAIL_RATIO` in Python: a second
    copy of that ratio is exactly the transcription drift this parity exists to
    prevent. The branch condition mirrors `stackGapPxForMoment`'s
    `claimQualifier` (`kind == "hook"` and `isClaimQualifierHook`), pinned
    branch-by-branch against the TypeScript source by
    `tests/contracts/test_persian_flat_hook.py`.
    """
    if claim_qualifier:
        if tail_px is None:
            raise ValueError(
                "claim_qualifier=True needs the fitted tail size (tail_px): "
                "without it the expectation would silently fall back to the "
                "lead derivation, which is the wrong design for a hook — "
                "36 × 0.55 = 20px against 37px painted."
            )
        return round(tail_px * STACK_GAP_RATIO) * scale
    return round(lead_px * STACK_GAP_RATIO) * scale


def measure_stack_rhythm(
    frame: np.ndarray,
    *,
    lead_px: float,
    tail_px: float | None = None,
    claim_qualifier: bool = False,
    fmt: PersianFormat = "vertical",
    plateau_rows: tuple[int, int] | None = None,
    stack_height_px: float | None = None,
) -> dict[str, Any]:
    """Measure the visible gaps between a moment's blocks, against the design.

    ## The defect this quantifies

    The shipped render put 133px of empty space between a 260px numeral and the
    line beneath it, against a designed `stackGapPx` of 26 — five times the
    design, invisible in the props, and reported by the user as «یه فاصله
    مسخره و زیاد به این خط و کلمه‌ها». The cause was not a wrong gap value but
    *half-leading*: Estedad's line box is 1.665em while a numeral's ink is
    ~0.97em, so a row laid out by its line box carries leading that belongs to no
    glyph, and the flex gap was measured between boxes rather than between ink.

    The fix trims each row onto its measured ink (see `inkTrimMargins`), so a
    declared gap is the gap that appears. This function is the check that the
    trim actually happened: it finds the ink bands in the frame, measures the
    empty rows between consecutive bands, and compares each against the designed
    gap with a tolerance for encoder noise and antialiasing.

    The expectation mirrors `stackGapPxForMoment` in `layout.ts`: an ordinary
    moment's gap derives from the lead size, while a claim+qualifier hook's gap
    derives from the fitted qualifier (`tail_px`) — the gap sits between the
    claim and the qualifier, and deriving it from the lead would understate the
    design (20px against 37px painted on the approved hook). Callers thread the
    shape through `claim_qualifier` (the conjunction of the declared
    `kind == "hook"` and the `hero`+`tail`, no-`accentWords` structure —
    `is_claim_qualifier_hook` in `lib/persian_moments.py`, kept in parity with
    `isClaimQualifierHook`) together with the fitted `tail_px`. See
    `expected_stack_gap_px`, which carries the derivation so both branches are
    pinned contractually rather than inlined here.

    ## Why tolerance is generous in one direction only

    A band gap larger than `designed + tolerance` is the leading-leak failure —
    the direction nobody wants and the one this check exists for. A gap smaller
    than `designed − tolerance` can be legitimate: glyph descenders reach into
    the gap from the block above (a final «ی» dips below the baseline), and the
    hairline rule participates in the stack too. So the check is one-sided,
    reporting only gaps that are *too large*, and it reports the measurement
    rather than a boolean so a reviewer can see by how much.
    """
    from lib.persian_moments import PersianMoment  # local import: avoid a cycle

    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape
    plateau_top, plateau_bottom = _resolve_plateau(
        width, height, fmt, plateau_rows, stack_height_px
    )
    zone_top, zone_bottom = moment_zone(width, height, fmt)
    scale = width / FORMAT_DIMENSIONS[fmt][0]

    band_slice = slice(plateau_top, plateau_bottom)
    mask = ink_mask(array)[band_slice]
    row_counts = mask.sum(axis=1)

    bands = _ink_row_runs(row_counts, min_run_ink=max(4, int(round(MIN_LINE_PX[fmt] * scale))))
    if len(bands) < 2:
        return {
            "checked": False,
            "reason": "fewer than two ink bands in the plateau; rhythm needs a stack "
            "to measure",
        }

    gaps = [
        float((lo - bands[i][1] - 1))
        for i in range(len(bands) - 1)
        for lo in (bands[i + 1][0],)
    ]
    designed_px = expected_stack_gap_px(
        lead_px, tail_px=tail_px, claim_qualifier=claim_qualifier, scale=scale
    )
    tolerance_px = max(14.0, 0.5 * designed_px)

    oversize = [
        gap for gap in gaps if gap > designed_px + tolerance_px
    ]
    result: dict[str, Any] = {
        "checked": True,
        "band_gaps_px": [round(gap, 1) for gap in gaps],
        "designed_gap_px": round(designed_px, 1),
        "tolerance_px": round(tolerance_px, 1),
        "oversize_gaps": [round(gap, 1) for gap in oversize],
        "problems": [],
    }
    if oversize:
        worst = max(oversize)
        result["problems"].append(
            f"a band gap is {worst:.0f}px against a designed {designed_px:.0f}px "
            f"(+{tolerance_px:.0f}px tolerance) — leading is leaking into the gap, "
            "which is the «فاصله مسخره» failure: the row was laid out by its line "
            "box instead of its ink. Check the ink-trim margins in the component."
        )
    result["passed"] = not result["problems"]
    return result


# --- Watermark detection -----------------------------------------------------------
#
# The watermark is drawn straight onto the footage with no scrim behind it, so none of
# the thresholds above apply to it: `SCRIM_CEILING` is a bound the scrim supplies, and
# there is no scrim here. See `find_watermark` for why appearance-based detection does
# not work for the mark at all.

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
    frames: Sequence[tuple[str, np.ndarray]],
    fmt: PersianFormat = "vertical",
    plateau_rows: dict[str, tuple[int, int]] | None = None,
    stack_heights_px: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Measure a set of labelled frames and summarize.

    Answers the question the compose stage has: is there any frame where a moment
    rendered wrongly?

    Frames with no text are **not** failures, and that is a bigger deal here than it was
    under the caption model. Text now covers at most 55% of the runtime by design, so a
    blindly sampled frame is more likely than not to be empty. The caller states which
    frames should carry a moment by passing them; a set where *no* frame has text is
    still reported, since that means either the sampling missed every moment or the
    render has no type in it at all.

    When a moment's fitted ``stack_height_px`` is known, pass it via
    ``stack_heights_px[label]`` (or ``plateau_rows[label]``) so the measurement is
    scoped to the scrim plateau that the frame's moment actually darkened.
    """
    measurements: dict[str, dict[str, Any]] = {}
    problems: list[str] = []

    for label, frame in frames:
        p_rows = (plateau_rows or {}).get(label) if plateau_rows else None
        s_px = (stack_heights_px or {}).get(label) if stack_heights_px else None
        measurement = measure_moment(
            frame, fmt, plateau_rows=p_rows, stack_height_px=s_px
        )
        measurements[label] = measurement.to_dict()
        problems.extend(f"{label}: {problem}" for problem in measurement.problems)

    with_text = [label for label, data in measurements.items() if data["glyph_pixels"]]
    if frames and not with_text:
        problems.append(
            "no sampled frame contains moment text. Sample frames chosen from the "
            "moment list's own timings rather than at fixed intervals — under the moment "
            "model nearly half the runtime is deliberately empty — and if those are "
            "empty too, the font failed to load and the type is tofu."
        )

    return {
        "frames": measurements,
        "frames_with_text": with_text,
        "problems": problems,
        "passed": not problems,
    }


def check_gap_is_empty(
    frame: np.ndarray, fmt: PersianFormat = "vertical"
) -> dict[str, Any]:
    """Confirm a frame sampled between moments carries no typographic hero.

    The gaps are the model — nearly half the runtime is deliberately empty — so this is
    the check that the emptiness is real, and it needs a different instrument from every
    other check here. A gap frame has no scrim, by design, so `ink_mask` sees raw footage
    and returns 31-99% "ink" on the real render. Brightness cannot answer the question.

    Accent coverage can. `accent_mask` is a colour test, not a contrast test — the
    accent's channel spread of 180 admits 0.0000% of real footage — so it works with no
    scrim behind it. Measured on the real render: nine gap frames carry 0.0000-0.0246%
    accent, thirteen moment frames with a figure or a term carry 3.84-7.93% (the frames
    the ceiling was calibrated on).

    Every moment paints its hero in the accent, so an overrun of any kind spilling
    accent ink into the gap trips this ceiling. What this still cannot see is a gap
    overrun that paints *no* accent ink — neutral-only residue with the hero fully
    exited — because neutral ink over unscrimmed footage is indistinguishable from
    the footage, and no threshold separates them without firing on bright clips.
    """
    array = np.asarray(frame, dtype=int)
    height, width, _ = array.shape
    zone_top, zone_bottom = moment_zone(width, height, fmt)

    accent = accent_mask(array)[zone_top:zone_bottom]
    fraction = float(accent.mean())

    result: dict[str, Any] = {
        "accent_fraction": round(fraction, 6),
        "ceiling": GAP_ACCENT_CEILING,
        "detects": "any moment kind's accent hero spilling into the gap; neutral-only "
        "residue with the hero fully exited is not separable from unscrimmed footage",
        "problems": [],
    }
    if fraction > GAP_ACCENT_CEILING:
        result["problems"].append(
            f"{fraction:.2%} of the moment zone is accent ink, against "
            f"{GAP_ACCENT_CEILING:.1%} allowed and under 0.03% on every real gap frame. "
            "A moment of any kind is still painting here, so a moment overran its exit or "
            "two moments overlap — check the moment timings against "
            "`MOMENT_MIN_GAP_SECONDS`."
        )
    result["passed"] = not result["problems"]
    return result


def anchor_report(
    frames: Sequence[tuple[str, np.ndarray]],
    fmt: PersianFormat = "vertical",
    plateau_rows: dict[str, tuple[int, int]] | None = None,
    stack_heights_px: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Summarize how well every measured line held the right anchor.

    Separate from `verify_frames` because it answers a different question. That one asks
    "did anything fail"; this one asks "how close is the type to its spine across the
    whole video", which is the number that shows a slow drift before it becomes a
    failure on one frame.
    """
    offsets: list[float] = []
    per_frame: dict[str, float | None] = {}

    for label, frame in frames:
        p_rows = (plateau_rows or {}).get(label) if plateau_rows else None
        s_px = (stack_heights_px or {}).get(label) if stack_heights_px else None
        measurement = measure_moment(frame, fmt, plateau_rows=p_rows, stack_height_px=s_px)
        per_frame[label] = (
            round(measurement.worst_anchor_offset_px, 1)
            if measurement.worst_anchor_offset_px is not None
            else None
        )
        offsets.extend(measurement.anchor_offsets_px)

    if not offsets:
        return {"lines_measured": 0, "per_frame": per_frame}

    return {
        "lines_measured": len(offsets),
        "median_offset_px": round(float(np.median(offsets)), 1),
        "worst_offset_px": round(max(offsets), 1),
        "tolerance_px": ANCHOR_TOLERANCE_PX,
        "per_frame": per_frame,
    }
