/**
 * Canvas text measurement for Persian, memoized.
 *
 * Why measure at all, when the browser can wrap text itself: CSS wrapping is
 * greedy and font-agnostic, so it breaks a Persian line wherever the box runs
 * out — including after «به» or before «را», which a Persian reader perceives as
 * a typesetting error rather than a wrap. Choosing break points ourselves
 * (`layout.ts`) requires knowing the real pixel width of every candidate line,
 * which only the font can answer.
 *
 * The module also measures **ink height**, which the width-only predecessor did
 * not, and that omission is why the shipped render had 133px of unexplained space
 * between a numeral and the line under it. See `measureInk`.
 *
 * Two invariants are enforced here rather than documented and hoped for:
 *
 * 1. **Never measure before Estedad is registered.** `measurePersian` throws if
 *    the font is not loaded. A fallback measurement produces widths for the
 *    wrong typeface and every downstream break decision is wrong, silently.
 * 2. **Never measure the painted string.** Estedad has no ZWNJ glyph, so a
 *    string containing one may be charged a `.notdef` advance. Measurement uses
 *    `measurableText()`; rendering uses the original.
 */

import { estedadCanvasFont, isEstedadLoaded, type EstedadWeight } from "./fonts";
import {
  FONT_ASCENT_EM,
  FONT_DESCENT_EM,
  ZWNJ_PAINT_CHARGE_EM,
} from "./tokens";
import { measurableText } from "./text";

/**
 * One canvas reused for every measurement.
 *
 * Allocating a canvas per call is slow enough to matter: a 60-second video with
 * per-word measurement runs into thousands of calls per frame-independent layout
 * pass, and each `document.createElement("canvas")` forces a GPU-backed surface.
 */
let sharedContext: CanvasRenderingContext2D | null = null;

function context(): CanvasRenderingContext2D {
  if (sharedContext) return sharedContext;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error(
      "Could not acquire a 2D canvas context for text measurement. " +
        "Persian layout cannot be computed without it.",
    );
  }
  sharedContext = ctx;
  return ctx;
}

/**
 * Memo cache keyed by the exact measurement inputs.
 *
 * Keyed on `weight|size|text` because all three change the advance width.
 * A plain object would collide with keys like `"constructor"`; a Map does not.
 */
const cache = new Map<string, number>();

/** Separate cache for ink boxes, keyed the same way. */
const inkCache = new Map<string, InkBox>();

function assertFontReady(what: string): void {
  if (!isEstedadLoaded()) {
    throw new Error(
      `${what} called before Estedad finished loading. Await \`estedadReady\` ` +
        "from ./fonts first — measuring against a fallback font silently produces " +
        "wrong line breaks and wrong vertical rhythm for the whole video.",
    );
  }
}

/**
 * Width in CSS pixels of `text` rendered in Estedad at `fontSizePx`/`weight`.
 *
 * @throws if Estedad has not finished loading — see the module comment.
 */
export function measurePersian(
  text: string,
  fontSizePx: number,
  weight: EstedadWeight,
): number {
  assertFontReady("measurePersian()");

  const measurable = measurableText(text);
  if (measurable === "") return 0;

  const key = `${weight}|${fontSizePx}|${measurable}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;

  const ctx = context();
  ctx.font = estedadCanvasFont(fontSizePx, weight);
  const width = ctx.measureText(measurable).width;
  cache.set(key, width);
  return width;
}

/**
 * Width of a sequence of words as the component will paint them.
 *
 * The component paints each word as its own `inline-block` span, separated by a
 * CSS flex `gap` of `wordGapRatio × fontSize`. That layout cannot kern across
 * the gap the way one joined run does, so a joined `measureText` of the whole
 * line disagrees with the paint — measured at 2–3% under on a 903px budget,
 * which is a 24px overflow on a line that "fit". Measuring the paint means
 * measuring per span and adding the rendered gap per boundary:
 *
 *     Σ advance(word) + (n−1) × round(gapRatio × fontSize)
 *
 * A joined measure is still taken for the *probe* strings only (see
 * `spaceAdvance`), never for the answer.
 */
export function measureWords(
  words: readonly string[],
  fontSizePx: number,
  weight: EstedadWeight,
  wordGapRatio: number,
): number {
  if (words.length === 0) return 0;

  const renderedGapPx = Math.round(fontSizePx * wordGapRatio);
  let total = 0;
  for (const word of words) {
    total += measurePersian(word, fontSizePx, weight);
    // The DOM paints each word as an inline-block span with unicodeBidi:"embed".
    // In that path Chromium charges ZWNJ (U+200C) as a .notdef advance that the
    // canvas shaping path does not. The charge is context-dependent (0.30–0.53em
    // observed); billed at the observed max so the fitter never undercounts.
    const zwnjCount = (word.match(/\u200C/g) ?? []).length;
    total += Math.round(zwnjCount * ZWNJ_PAINT_CHARGE_EM * fontSizePx);
  }
  return total + (words.length - 1) * renderedGapPx;
}

/**
 * The real ink box of one line, relative to its alphabetic baseline.
 *
 * `abovePx` and `belowPx` are both non-negative distances from the baseline, so
 * `abovePx + belowPx` is the height of the smallest rectangle containing every
 * painted pixel of the line.
 */
export interface InkBox {
  readonly abovePx: number;
  readonly belowPx: number;
  readonly widthPx: number;
}

/**
 * Measure the real painted extent of a line.
 *
 * ## Why this exists
 *
 * A text row's *box* is `line-height` tall and its glyphs sit inside that box
 * wherever the font's baseline puts them. Estedad's natural line box is 1.665em
 * while a Persian numeral's real ink is about 0.97em, so laying out a 260px
 * numeral leaves roughly 180px of leading that belongs to no glyph. Stacking such
 * rows and declaring a 26px gap between them produces a *visible* gap of over
 * 130px — which is precisely the defect the shipped render showed between a
 * figure and its label, and it cannot be fixed by choosing a better line-height
 * multiplier because the slack depends on which glyphs are in the string.
 *
 * With the real box known, a row can be trimmed to its ink with negative margins
 * and a declared gap becomes the gap that appears. Everything else in the
 * vertical rhythm depends on this function being real measurement rather than an
 * em-based estimate.
 *
 * ## Why `actualBoundingBox*` and not the font metrics
 *
 * `fontBoundingBoxAscent/Descent` describe the *font*, identically for every
 * string, which is the estimate that produced the problem. `actualBoundingBox*`
 * describes *these glyphs*. The distinction is the whole point.
 *
 * A string with no ink at all (a lone ZWNJ, an empty line) has a zero-height box
 * rather than a font-height one, so a stray empty row contributes nothing to the
 * stack instead of silently adding a line of leading.
 */
export function measureInk(
  text: string,
  fontSizePx: number,
  weight: EstedadWeight,
): InkBox {
  assertFontReady("measureInk()");

  const measurable = measurableText(text);
  const key = `${weight}|${fontSizePx}|${measurable}`;
  const hit = inkCache.get(key);
  if (hit !== undefined) return hit;

  if (measurable === "") {
    const empty: InkBox = { abovePx: 0, belowPx: 0, widthPx: 0 };
    inkCache.set(key, empty);
    return empty;
  }

  const ctx = context();
  ctx.font = estedadCanvasFont(fontSizePx, weight);
  ctx.textBaseline = "alphabetic";
  const metrics = ctx.measureText(measurable);

  // `actualBoundingBoxAscent` is positive above the baseline and
  // `actualBoundingBoxDescent` is positive below it. Both can legitimately be
  // negative — an all-superscript string has no ink below the baseline, so its
  // descent is negative — and a negative contribution to a height is nonsense, so
  // both are floored at zero.
  //
  // The fallback matters: `actualBoundingBox*` is undefined in older engines and
  // in some headless configurations, and a NaN here would propagate into every
  // margin in the stack and produce a blank frame with no error. Falling back to
  // the font box over-reserves space, which is the old behaviour — visibly loose
  // but never broken.
  const above = Number.isFinite(metrics.actualBoundingBoxAscent)
    ? Math.max(0, metrics.actualBoundingBoxAscent)
    : fontSizePx * FONT_ASCENT_EM;
  const below = Number.isFinite(metrics.actualBoundingBoxDescent)
    ? Math.max(0, metrics.actualBoundingBoxDescent)
    : fontSizePx * FONT_DESCENT_EM;

  const box: InkBox = { abovePx: above, belowPx: below, widthPx: metrics.width };
  inkCache.set(key, box);
  return box;
}

/** Clear the memo caches. For tests and font reloads only. */
export function resetMeasurementCache(): void {
  cache.clear();
  inkCache.clear();
  sharedContext = null;
}
