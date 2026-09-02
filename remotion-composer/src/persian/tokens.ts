/**
 * Design tokens for the Persian composition.
 *
 * Two format targets share one token set: vertical 1080×1920 (the default) and
 * landscape 1920×1080 (long-form YouTube). Type sizes are therefore expressed
 * per format rather than as one scale with a multiplier — a single scale factor
 * cannot serve both, because the constraint differs in kind. Vertical is
 * *width*-bound: a phone screen forces large type or nothing is readable at
 * arm's length. Landscape is *distance*-bound: the same physical text is read
 * from further away on a bigger screen, so it needs proportionally less of the
 * frame.
 *
 * ## Why the type scale is not copied from `youtube-videos`
 *
 * That project's scale is tuned for Plus Jakarta Sans, a Latin face. Persian
 * glyph metrics differ in ways that make a Latin scale read wrong:
 * ascender/descender extents are larger relative to x-height, letters join
 * horizontally so a word's width grows faster than its Latin character count
 * suggests, and diacritics sit above the cap line. Estedad at a Latin face's
 * "body" size looks oversized and crowds its own line box. The sizes below are
 * set for Estedad specifically, with line-heights loose enough for the
 * above-baseline marks.
 */

export type PersianFormat = "vertical" | "landscape";

export const FORMAT_DIMENSIONS: Record<
  PersianFormat,
  { readonly width: number; readonly height: number }
> = {
  vertical: { width: 1080, height: 1920 },
  landscape: { width: 1920, height: 1080 },
};

/**
 * Palette.
 *
 * Deliberately narrow. Footage supplies the colour in this pipeline; the
 * typographic layer stays near-monochrome so it reads over any clip. The single
 * accent is reserved for karaoke highlight and nothing else — an accent used for
 * two purposes stops signalling either.
 */
export const PERSIAN_PALETTE = {
  /** Subtitle body. Pure white, because it sits over unpredictable footage. */
  text: "#FFFFFF",
  /** Karaoke highlight / emphasis. High-chroma yellow survives any background. */
  highlight: "#FFEA00",
  /** Hook emphasis. Used only in the opening beat. */
  hookEmphasis: "#FF2E2E",
  /** Watermark glow, as an "R, G, B" triplet for rgba() interpolation. */
  watermarkGlowRgb: "255, 215, 0",
  /** Typographic-beat background, for cues with no footage. */
  voidBackground: "#0B0B0C",
} as const;

/**
 * Glass subtitle panel.
 *
 * A frosted panel rather than a text shadow, because a shadow over moving
 * footage fails intermittently: it works on a dark frame and disappears on a
 * bright one, so readability flickers shot to shot. A blurred panel establishes
 * its own local contrast, so the same text is legible over any clip.
 *
 * The values are the ones proven in `reels-videos-v2.1.6`. Two are load-bearing
 * and worth stating: the inset white hairline at 5% is what keeps the panel from
 * looking like a grey rectangle (it reads as a lit edge), and `boxSizing:
 * border-box` is required because the padding is large — without it the panel
 * exceeds `maxWidth` and the measured line budget no longer matches the painted
 * box.
 */
export const GLASS = {
  backgroundColor: "rgba(20, 20, 20, 0.45)",
  blurPx: 12,
  borderRadiusPx: 24,
  boxShadow:
    "inset 0px 0px 0px 1px rgba(255,255,255,0.05), 0px 10px 30px rgba(0,0,0,0.3)",
  /** Fraction of frame width the panel may occupy. */
  maxWidthFraction: 0.85,
} as const;

export interface FormatTypography {
  /** Subtitle body size in px. */
  readonly subtitleFontSizePx: number;
  /** Subtitle line-height as a multiplier. */
  readonly subtitleLineHeight: number;
  /** Horizontal gap between words, px. */
  readonly wordGapPx: number;
  /** Glass panel padding, "vertical horizontal" in px. */
  readonly glassPaddingPx: readonly [number, number];
  /** Distance from the frame bottom to the panel bottom, px. */
  readonly subtitleBottomPx: number;
  /** Hook line size in px. */
  readonly hookFontSizePx: number;
  /** Watermark size in px. */
  readonly watermarkFontSizePx: number;
  /** Maximum subtitle lines before layout escalates. */
  readonly maxLines: number;
  readonly maxLinesEscalated: number;
}

export const TYPOGRAPHY: Record<PersianFormat, FormatTypography> = {
  /**
   * Vertical. Sized for a phone held at arm's length, where the readable floor
   * is roughly 4.5% of frame width — 48px at 1080. 52px sits just above it with
   * headroom for the fitter's soft shrink to 0.92 (≈48px) without crossing it.
   */
  vertical: {
    subtitleFontSizePx: 52,
    subtitleLineHeight: 1.4,
    wordGapPx: 14,
    glassPaddingPx: [20, 75],
    // Clear of a phone UI's bottom chrome and of platform caption overlays,
    // which sit in the lowest ~15% on Reels and Shorts.
    subtitleBottomPx: 590,
    hookFontSizePx: 63,
    watermarkFontSizePx: 24,
    maxLines: 3,
    maxLinesEscalated: 4,
  },
  /**
   * Landscape. Read from further away on a larger screen, so type takes a
   * smaller share of the frame. Lines are wider, so the line cap drops to 2 —
   * a 1600px-wide Persian line at three lines is a wall of text, and the eye
   * loses its place tracking back across it in RTL.
   */
  landscape: {
    subtitleFontSizePx: 46,
    subtitleLineHeight: 1.45,
    wordGapPx: 12,
    glassPaddingPx: [18, 60],
    subtitleBottomPx: 110,
    hookFontSizePx: 72,
    watermarkFontSizePx: 26,
    maxLines: 2,
    maxLinesEscalated: 3,
  },
};

/**
 * Safe area as a fraction of each edge.
 *
 * Vertical reserves a large bottom margin for platform UI (the caption, the
 * author handle, the action rail all overlay the lowest fifth on Reels/Shorts/
 * TikTok) and a smaller top margin for the status bar. Landscape uses a uniform
 * margin, since YouTube overlays only a thin control bar that auto-hides.
 */
export const SAFE_AREA: Record<
  PersianFormat,
  { readonly top: number; readonly bottom: number; readonly side: number }
> = {
  vertical: { top: 0.08, bottom: 0.2, side: 0.06 },
  landscape: { top: 0.08, bottom: 0.08, side: 0.08 },
};

/** Text shadow beneath subtitle glyphs, layered under the glass panel. */
export const SUBTITLE_TEXT_SHADOW = "0px 2px 5px rgba(0,0,0,0.9)";

/**
 * Karaoke emphasis.
 *
 * `activeScale` is applied to the *word* during its spoken window. This is the
 * one place a transform on text is allowed, and only because the word is
 * actively changing rather than settled — the eye is tracking the change, so the
 * momentary edge re-snap is not perceptible as shimmer.
 *
 * `font-weight` is deliberately absent. Switching weight mid-line changes every
 * glyph advance, so the line re-wraps under the karaoke cursor and the text
 * visibly jitters. Emphasis is scale plus glow only, both of which leave the
 * measured width untouched.
 */
export const KARAOKE = {
  activeScale: 1.08,
  /** Frames of ramp at each edge of a word's window, so emphasis is not a snap. */
  edgeFrames: 3,
  glowRadiusPx: 18,
} as const;

/** Reading-speed ceiling in visible characters per second. */
export const MAX_CPS = 21;

/**
 * Top of the rows the subtitle panel can occupy, as a fraction of frame height.
 *
 * Derived from the same tokens the panel lays itself out from, so nothing else has to
 * restate the geometry to stay clear of it. The escalated line cap is used rather than
 * the normal one: a four-line cue is rare but legal, and something positioned against
 * the three-line height would collide only on those rare cues.
 *
 * This existed because it was needed. The watermark's quiet position was a flat 75%,
 * which is below the panel in vertical and *inside* it in landscape, where the panel
 * sits 110px from the bottom instead of 590px. Two formats, one hard-coded number, and
 * the collision appeared only in the format nobody had rendered yet.
 */
export function computeSubtitleBandTopFraction(format: PersianFormat): number {
  const { height } = FORMAT_DIMENSIONS[format];
  const typography = TYPOGRAPHY[format];
  const panelHeight =
    2 * typography.glassPaddingPx[0] +
    typography.maxLinesEscalated *
      typography.subtitleFontSizePx *
      typography.subtitleLineHeight;
  return (height - typography.subtitleBottomPx - panelHeight) / height;
}

/**
 * Where the watermark rests after migrating, as a percentage of frame height.
 *
 * Vertical goes near the top, clear of the subtitle panel. Landscape goes higher still,
 * clear of YouTube's control bar.
 */
export const WATERMARK_RESTING_TOP_PCT: Record<PersianFormat, number> = {
  vertical: 15,
  landscape: 8,
};

/**
 * Gap between the quiet watermark and the top of the subtitle band, as a percentage of
 * frame height. Enough that the bloom's scale-up cannot reach into the panel — the mark
 * grows about its own centre, so half the growth travels upward.
 */
export const WATERMARK_QUIET_CLEARANCE_PCT = 6;

/**
 * The watermark's quiet position, as a percentage of frame height.
 *
 * Derived, because a single hard-coded value cannot serve both formats. It was 75%:
 * correct in vertical, where the band starts at 52%, and *inside the band* in landscape,
 * where the panel sits 110px from the bottom instead of 590px and the band starts at
 * 68%. The mark overlapped the first line of every landscape subtitle, and looked
 * perfect in the format that had been rendered.
 *
 * Exported rather than inlined in the component so the verifier can search the position
 * the renderer actually uses.
 */
export function computeWatermarkQuietTopPct(format: PersianFormat): number {
  return Math.max(
    WATERMARK_RESTING_TOP_PCT[format],
    computeSubtitleBandTopFraction(format) * 100 - WATERMARK_QUIET_CLEARANCE_PCT,
  );
}

/** Overscale reserved so a karaoke-scaled word cannot exceed the line budget. */
export const KARAOKE_WIDTH_RESERVE = KARAOKE.activeScale;

/** Safety margin subtracted from the measured line budget, px. */
export const FIT_SAFETY_PX = 4;

/**
 * Usable text width inside the glass panel, in px.
 *
 * Derived rather than configured, so the panel geometry and the layout budget
 * cannot disagree. They disagreeing is the classic failure: text measured
 * against a width wider than the box it lands in, overflowing on exactly the
 * cues that are close to the limit.
 */
export function computeLineBudgetPx(format: PersianFormat): number {
  const { width } = FORMAT_DIMENSIONS[format];
  const typography = TYPOGRAPHY[format];
  const panelWidth = width * GLASS.maxWidthFraction;
  const horizontalPadding = typography.glassPaddingPx[1] * 2;
  return panelWidth - horizontalPadding - FIT_SAFETY_PX;
}
