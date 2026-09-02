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
  if (!isEstedadLoaded()) {
    throw new Error(
      "measurePersian() called before Estedad finished loading. Await " +
        "`estedadReady` from ./fonts first — measuring against a fallback font " +
        "silently produces wrong line breaks for the whole video.",
    );
  }

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
 * Width of a sequence of words joined by single spaces.
 *
 * Measures the joined string in one call rather than summing per-word widths.
 * Summing is wrong for Persian: adjacent letters join and kern, so a word's
 * isolated advance differs from its advance in context, and the error accumulates
 * across a line in the direction that makes text overflow.
 */
export function measureWords(
  words: readonly string[],
  fontSizePx: number,
  weight: EstedadWeight,
): number {
  if (words.length === 0) return 0;
  return measurePersian(words.join(" "), fontSizePx, weight);
}

/** Clear the memo cache. For tests and font reloads only. */
export function resetMeasurementCache(): void {
  cache.clear();
  sharedContext = null;
}
