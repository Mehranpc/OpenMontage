/**
 * Persian line breaking and block fitting.
 *
 * ## Why not CSS
 *
 * The browser wraps greedily: it fills a line until the next word does not fit,
 * then breaks. That is font-aware but grammar-blind, so it happily ends a line
 * on «به» or starts one with «را» — which a Persian reader reads as a broken
 * line, not a wrap. It also produces badly ragged blocks, because a greedy pass
 * has no way to trade slack between lines.
 *
 * So breaks are chosen here, by dynamic programming over measured widths, with
 * the grammatical rules from `./text` applied as hard constraints.
 *
 * ## Why grammar is a constraint and raggedness is a cost
 *
 * The objective is the sum of squared slack per line — the standard Knuth-Plass
 * shape, which spreads leftover space evenly instead of dumping it all on the
 * last line. On a 900px line those squared terms reach the tens of thousands.
 * Any grammatical "penalty" small enough to be a preference would be invisible
 * against that; any penalty large enough to win would be a constraint wearing a
 * costume, and would also distort the raggedness comparison between the
 * candidates that remain. Cleaner to prune forbidden breaks from the search
 * entirely and let the cost function do one job.
 *
 * ## The escalation ladder
 *
 * A block that does not fit is not a failure to report — it must still render.
 * `fitBlock` escalates in order of how visible the compromise is: use more
 * lines, then shrink slightly, then shrink hard. Shrinking is last because
 * inconsistent type size across cues is more noticeable than an extra line.
 */

import { measureWords } from "./measure";
import type { EstedadWeight } from "./fonts";
import { breakClass, splitWords } from "./text";

/** Squared-slack cost is meaningless past this; used to mark impossible states. */
const INFEASIBLE = Number.POSITIVE_INFINITY;

export interface LayoutConstraints {
  /** Usable text width in CSS px — panel width minus padding minus safety. */
  readonly maxWidthPx: number;
  /** Preferred maximum line count before escalation. */
  readonly maxLines: number;
  /** Hard ceiling on lines, used only after a soft shrink fails. */
  readonly maxLinesEscalated: number;
  readonly fontSizePx: number;
  readonly weight: EstedadWeight;
}

export interface LayoutResult {
  /** Words per line, in reading order. */
  readonly lines: string[][];
  /** Scale actually applied to `fontSizePx` (1 when no shrink was needed). */
  readonly fontScale: number;
  /** Widest laid-out line, in px at the applied scale. */
  readonly maxLineWidthPx: number;
  /**
   * Which rung of the escalation ladder produced this result. Recorded so the
   * reviewer can flag a video whose cues are constantly escalating — that means
   * the cue budget or the panel width is wrong upstream, not that this fitter
   * misbehaved.
   */
  readonly escalation: "none" | "more-lines" | "soft-shrink" | "hard-shrink";
}

/** Soft floor: below this, size differences between cues start to read. */
const MIN_FONT_SCALE = 0.92;
/** Hard floor. Past this, text is too small to read on a phone at arm's length. */
const ABSOLUTE_MIN_FONT_SCALE = 0.62;
/** Steps between the soft and hard floor. Coarse enough to stay fast. */
const SHRINK_STEPS = 8;

/**
 * Break `words` into at most `maxLines` lines, minimizing squared raggedness.
 *
 * Returns null when no legal break assignment exists — either a single word is
 * wider than the line, or every candidate break is grammatically forbidden.
 * Callers escalate; they must not silently render an overflowing line.
 *
 * Complexity is O(n²) in words per cue with a memoized width per span. Cues are
 * a dozen words at most, so this is microseconds, and it runs once per cue at
 * layout time rather than per frame.
 */
function breakIntoLines(
  words: readonly string[],
  constraints: LayoutConstraints,
  fontScale: number,
  maxLines: number,
): { lines: string[][]; maxLineWidthPx: number } | null {
  const n = words.length;
  if (n === 0) return { lines: [], maxLineWidthPx: 0 };

  const fontSize = constraints.fontSizePx * fontScale;
  const maxWidth = constraints.maxWidthPx;

  // width[i][j] = px width of words[i..j] joined by single spaces.
  // Measured as a joined string, not summed per word: Persian letters join and
  // kern across word boundaries, so summed isolated widths drift in the
  // direction that overflows.
  const width: number[][] = Array.from({ length: n }, () => new Array(n).fill(0));
  for (let i = 0; i < n; i += 1) {
    for (let j = i; j < n; j += 1) {
      width[i][j] = measureWords(words.slice(i, j + 1), fontSize, constraints.weight);
    }
  }

  /**
   * A break between words[j] and words[j+1] is legal only if grammar allows it.
   * An authored "\n" token forces a break and is never itself placed on a line.
   */
  const legalBreakAfter = (j: number): boolean => {
    if (j === n - 1) return true;
    if (words[j + 1] === "\n") return true;
    if (words[j] === "\n") return true;
    return breakClass(words[j], words[j + 1]) !== "forbidden";
  };
  const forcedBreakAfter = (j: number): boolean =>
    j < n - 1 && (words[j + 1] === "\n" || words[j] === "\n");

  const preferredBreakAfter = (j: number): boolean =>
    j < n - 1 && words[j + 1] !== "\n" && breakClass(words[j], words[j + 1]) === "preferred";

  /**
   * best[k][i] = minimum cost of laying out words[i..] in at most k lines.
   * choice[k][i] = index of the last word on the first of those lines.
   */
  const best: number[][] = Array.from({ length: maxLines + 1 }, () =>
    new Array(n + 1).fill(INFEASIBLE),
  );
  const choice: number[][] = Array.from({ length: maxLines + 1 }, () =>
    new Array(n + 1).fill(-1),
  );

  for (let k = 0; k <= maxLines; k += 1) best[k][n] = 0;

  for (let k = 1; k <= maxLines; k += 1) {
    for (let i = n - 1; i >= 0; i -= 1) {
      // Skip a leading forced-break token: it is a separator, not a word.
      if (words[i] === "\n") {
        best[k][i] = best[k][i + 1];
        choice[k][i] = i;
        continue;
      }

      for (let j = i; j < n; j += 1) {
        if (words[j] === "\n") break;
        const lineWidth = width[i][j];
        if (lineWidth > maxWidth) break; // wider spans only get worse
        if (!legalBreakAfter(j)) continue;

        const isLastLine = j === n - 1;
        // Squared slack, except on the final line: a short last line is correct
        // typography, not raggedness, so charging it would push the breaker to
        // pad the ending unnaturally.
        const slack = maxWidth - lineWidth;
        let cost = isLastLine ? 0 : slack * slack;
        // Bounded bonus for a natural pause. Scaled to the cost surface so it
        // can break ties between near-equal layouts without ever overriding a
        // genuinely better-balanced one.
        if (!isLastLine && preferredBreakAfter(j)) {
          cost *= 0.85;
        }

        const rest = best[k - 1][j + 1];
        if (rest === INFEASIBLE) continue;

        const total = cost + rest;
        if (total < best[k][i]) {
          best[k][i] = total;
          choice[k][i] = j;
        }

        if (forcedBreakAfter(j)) break;
      }
    }
  }

  if (best[maxLines][0] === INFEASIBLE) return null;

  const lines: string[][] = [];
  let index = 0;
  let remaining = maxLines;
  let maxLineWidthPx = 0;
  while (index < n && remaining > 0) {
    const end = choice[remaining][index];
    if (end < 0) return null;
    if (words[index] === "\n") {
      index += 1;
      continue;
    }
    lines.push(words.slice(index, end + 1));
    maxLineWidthPx = Math.max(maxLineWidthPx, width[index][end]);
    index = end + 1;
    remaining -= 1;
  }
  if (index < n) return null;

  return { lines, maxLineWidthPx };
}

/**
 * Lay out one cue, escalating until it fits.
 *
 * The ladder, in order of increasing visibility to a viewer:
 *   1. `maxLines` at full size — the intended result.
 *   2. `maxLinesEscalated` at full size — one more line is barely noticeable.
 *   3. Shrink toward `MIN_FONT_SCALE` — slight, still visually consistent.
 *   4. Shrink toward `ABSOLUTE_MIN_FONT_SCALE` — visible, but readable.
 *
 * Throws only if step 4 also fails, which means a single word does not fit at
 * 62% of the intended size. That is a content problem (a URL, an unbroken
 * compound) that must be fixed upstream rather than papered over, and failing
 * loudly here is how it gets noticed before render rather than after.
 */
export function fitBlock(
  text: string,
  constraints: LayoutConstraints,
): LayoutResult {
  const words = splitWords(text);
  if (words.length === 0) {
    return { lines: [], fontScale: 1, maxLineWidthPx: 0, escalation: "none" };
  }

  const attempt = breakIntoLines(words, constraints, 1, constraints.maxLines);
  if (attempt) {
    return { ...attempt, fontScale: 1, escalation: "none" };
  }

  const wider = breakIntoLines(words, constraints, 1, constraints.maxLinesEscalated);
  if (wider) {
    return { ...wider, fontScale: 1, escalation: "more-lines" };
  }

  for (let step = 1; step <= SHRINK_STEPS; step += 1) {
    const scale = 1 - ((1 - MIN_FONT_SCALE) * step) / SHRINK_STEPS;
    const shrunk = breakIntoLines(
      words,
      constraints,
      scale,
      constraints.maxLinesEscalated,
    );
    if (shrunk) {
      return { ...shrunk, fontScale: scale, escalation: "soft-shrink" };
    }
  }

  for (let step = 1; step <= SHRINK_STEPS; step += 1) {
    const scale =
      MIN_FONT_SCALE -
      ((MIN_FONT_SCALE - ABSOLUTE_MIN_FONT_SCALE) * step) / SHRINK_STEPS;
    const shrunk = breakIntoLines(
      words,
      constraints,
      scale,
      constraints.maxLinesEscalated,
    );
    if (shrunk) {
      return { ...shrunk, fontScale: scale, escalation: "hard-shrink" };
    }
  }

  throw new Error(
    `Persian cue cannot be laid out even at ${ABSOLUTE_MIN_FONT_SCALE}× size ` +
      `within ${constraints.maxWidthPx}px and ${constraints.maxLinesEscalated} lines. ` +
      `Usually one unbreakable token (a URL or a long compound) is wider than the ` +
      `panel. Fix the cue text upstream. Cue: ${JSON.stringify(text.slice(0, 80))}`,
  );
}

export const LAYOUT_FLOORS = {
  MIN_FONT_SCALE,
  ABSOLUTE_MIN_FONT_SCALE,
} as const;
