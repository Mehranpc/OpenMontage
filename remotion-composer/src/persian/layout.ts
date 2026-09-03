/**
 * Persian line breaking and moment fitting.
 *
 * Two layers live here:
 *
 *   1. `fitBlock` — break one string into measured lines. Grammar-aware,
 *      font-aware, unchanged in principle from the version this file replaces.
 *   2. `fitMoment` — choose **one** size for a whole moment and lay out every
 *      segment at the proportions that size implies. New, and the reason the file
 *      grew: the predecessor had no notion of a moment as a unit, so each segment
 *      was fitted independently against a per-kind fixed size and the stack's
 *      total height was nobody's concern.
 *
 * ## Why not CSS (for the breaking)
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
 * ## Why one size per moment, chosen by search
 *
 * The shipped render fixed a size per moment *kind*: every figure's hero was
 * 260px, every statement 80px, every scoping line 38px. Each number was
 * defensible on the example it was tuned against and the combinations were not:
 * a 38px accent line above an 80px claim is a 2.1:1 ratio that reads as a caption
 * with a label, and «۲۲۶۴» at 260px above «دانشگاه اولو، فنلاند» at 44px is 5.9:1,
 * which reads as two unrelated objects rather than one phrase. The user's report
 * named both — «سایز خط اول و دوم تناسب نداره» and «خط نارنجی بیش از حد کوچیکه».
 *
 * What the eye judges is the *ratio* between the parts of one phrase, so the ratio
 * is the designed constant (`LEAD_RATIO`) and the absolute size is whatever the
 * content allows. `fitMoment` walks `HERO_LADDER_PX` from the top and returns the
 * first rung where the whole composed stack — every segment, at that rung's
 * proportions, with real measured ink and real gaps — fits the width budget *and*
 * the height budget, except that a hook starts its walk below the top
 * (`HOOK_HERO_LADDER_OFFSET` for claim+qualifier, `FLAT_HERO_LADDER_OFFSET` for
 * flat display — see the full `fitMoment` doc). A short quantity lands high on
 * the ladder, a long claim lands lower, and in both cases the lead is the same
 * fraction of the hero.
 *
 * ## The escalation ladder, for one block
 *
 * A block that does not fit its own line budget is not a failure to report — it
 * must still render. `fitBlock` escalates in order of how visible the compromise
 * is: use more lines, then shrink slightly, then shrink hard. Shrinking is last
 * because inconsistent type size *inside one moment* is more noticeable than an
 * extra line. Note that `fitMoment` prefers dropping a ladder rung over letting
 * `fitBlock` shrink, because a rung change scales the whole moment coherently
 * while a shrink distorts one segment against its siblings.
 */

import { measureInk, measureWords, type InkBox } from "./measure";
import type { EstedadWeight } from "./fonts";
import { breakClass, splitWords, visibleLength } from "./text";
import {
  BLOCK_LEADING_RATIO,
  DISPLAY_LEADING_RATIO,
  FLAT_HERO_LADDER_OFFSET,
  FLAT_HERO_MAX_LINES,
  HERO_LADDER_PX,
  HERO_MAX_LINES,
  HOOK_HERO_LADDER_OFFSET,
  HOOK_TAIL_RATIO,
  HOOK_TAIL_WEIGHT,
  MAX_LEAD_LINES,
  MOMENT_RULE_HEIGHT_PX,
  PRESENCE_LIFT_STEP,
  SHORT_HERO_FILL_FRACTION,
  SHORT_HERO_MAX_CHARS,
  STACK_GAP_RATIO,
  TYPOGRAPHY,
  computeLeadPx,
  computeLineBudgetPx,
  computeMaxStackPx,
  computeShortHeroMaxPx,
  computeSourcePx,
  computeStackGapPx,
  type PersianFormat,
} from "./tokens";
import type {
  PersianMomentKind,
  PersianSegment,
  PersianSegmentRole,
} from "./types";

/** Squared-slack cost is meaningless past this; used to mark impossible states. */
const INFEASIBLE = Number.POSITIVE_INFINITY;

export interface LayoutConstraints {
  /** Usable text width in CSS px — the text column minus safety. */
  readonly maxWidthPx: number;
  /** Preferred maximum line count before escalation. */
  readonly maxLines: number;
  /** Hard ceiling on lines, used only after a soft shrink fails. */
  readonly maxLinesEscalated: number;
  readonly fontSizePx: number;
  readonly weight: EstedadWeight;
  /**
   * The rendered flex gap between words, as a fraction of the block's size.
   *
   * `measureWords` needs it because the paint does not use the font's space:
   * a line's real width is glyph advances plus this gap, per inter-word
   * boundary. See the comment there for the failure it caused when omitted.
   */
  readonly wordGapRatio: number;
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
   * reviewer can flag a video whose moments are constantly escalating — that
   * means the type scale or the text width is wrong upstream, not that this
   * fitter misbehaved.
   */
  readonly escalation: "none" | "more-lines" | "soft-shrink" | "hard-shrink";
}

/** Soft floor: below this, size differences between moments start to read. */
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
 * Complexity is O(n²) in words per block with a memoized width per span. A
 * statement is a dozen words at most, so this is microseconds, and it runs once
 * per moment at layout time rather than per frame.
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
      width[i][j] = measureWords(
        words.slice(i, j + 1),
        fontSize,
        constraints.weight,
        constraints.wordGapRatio,
      );
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
 * Lay out one text block, escalating until it fits.
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
    `Persian text block cannot be laid out even at ${ABSOLUTE_MIN_FONT_SCALE}× size ` +
      `within ${constraints.maxWidthPx}px and ${constraints.maxLinesEscalated} lines. ` +
      `Usually one unbreakable token (a URL or a long compound) is wider than the ` +
      `line budget. Fix the text upstream. Text: ${JSON.stringify(text.slice(0, 80))}`,
  );
}

export const LAYOUT_FLOORS = {
  MIN_FONT_SCALE,
  ABSOLUTE_MIN_FONT_SCALE,
} as const;

// ---------------------------------------------------------------------------
// Moment fitting
// ---------------------------------------------------------------------------

/** Weight per role. The hero carries the emphasis, so it carries the weight. */
export const ROLE_WEIGHT: Record<PersianSegmentRole, EstedadWeight> = {
  lead: 500,
  hero: 900,
  tail: 500,
  source: 500,
};

/**
 * Weight of a flat display hero — used only for a flat display block.
 *
 * Estedad Black at display size closes the counters of the Persian joining
 * letters and the words read as solid slabs, which is the "too heavy,
 * ill-proportioned" complaint; Bold keeps the authority without the blockiness.
 *
 * Critically, Estedad's Persian advance widths are identical across 500/700/900
 * (only Latin widens: 326.48/333.51/340.59px at 123px), so this changes ink
 * weight and ~10px of block height per step, and changes neither the ladder rung
 * nor the line break. That property is why the weight is safe to set
 * independently of the fit.
 *
 * Chosen by the same `isFlatDisplayBlock` predicate that governs the line cap
 * and the leading in `tryHeroSize`, so the three cannot drift apart.
 */
export const FLAT_DISPLAY_HERO_WEIGHT: EstedadWeight = 700;

/** One segment, laid out and measured. */
export interface FittedSegment {
  readonly role: PersianSegmentRole;
  readonly text: string;
  /** Seconds after the moment start at which this segment arrives. */
  readonly revealAfterSeconds: number;
  readonly fontSizePx: number;
  readonly weight: EstedadWeight;
  readonly lines: readonly string[][];
  /** Leading between this block's own lines, px. */
  readonly lineGapPx: number;
  /** Measured ink box per line, in the same order as `lines`. */
  readonly inkPerLine: readonly InkBox[];
  /**
   * Painted width per line, in the same order as `lines`.
   *
   * The `measureWords` basis — per-span advances plus the rendered word gaps
   * plus the ZWNJ paint charge — which is what the component actually puts on
   * screen. The ink advance alone undercounts a ZWNJ-containing line by up to
   * 0.53em per ZWNJ (36px on the approved hook's 68px qualifier), so a ratio
   * computed from advances would call the approved frame 0.58 while its pixels
   * measure 0.65. The silhouette gate reads this basis, not the advance.
   */
  readonly paintedWidthPerLine: readonly number[];
  /** Sum of measured ink heights plus internal leading, px. */
  readonly heightPx: number;
  /** Widest measured line, px. */
  readonly widthPx: number;
  /** Escalation this segment needed. `none` on every well-authored moment. */
  readonly escalation: LayoutResult["escalation"];
  /**
   * Inline accent words, carried through from `PersianSegment.accentWords`.
   *
   * Measurement never sees this — the whole block is measured and fitted as one
   * size, and only the paint consults the set. Carried rather than re-derived
   * because the fitted layer is the paint's only input.
   */
  readonly accentWords: readonly string[];
}

/** A whole moment, laid out at one coherent size. */
export interface FittedMoment {
  /** The hero rung chosen from `HERO_LADDER_PX`. */
  readonly heroPx: number;
  readonly leadPx: number;
  readonly sourcePx: number;
  /** Gap between two segments, px — real ink separation, not leading. */
  readonly stackGapPx: number;
  readonly segments: readonly FittedSegment[];
  /** Total ink height of the stack including the rule and every gap, px. */
  readonly heightPx: number;
  /** Widest line anywhere in the moment, px. */
  readonly widthPx: number;
  /** Index into the ladder. 0 is the largest rung; recorded for diagnostics. */
  readonly ladderIndex: number;
  /** Extra hero px added by the presence lift. 0 when the lift did not apply. */
  readonly presenceLiftPx: number;
}

function sizeForRole(
  role: PersianSegmentRole,
  heroPx: number,
  leadPx: number,
  sourcePx: number,
  tailPx: number,
): number {
  if (role === "hero") return heroPx;
  if (role === "source") return sourcePx;
  if (role === "tail") return tailPx;
  return leadPx;
}

function maxLinesForRole(role: PersianSegmentRole, flatDisplay: boolean): number {
  if (role === "hero") return flatDisplay ? FLAT_HERO_MAX_LINES : HERO_MAX_LINES;
  if (role === "source") return 1;
  return MAX_LEAD_LINES;
}

/**
 * Whether a moment's segments form a flat display block.
 *
 * A flat display block is a `hero` segment that carries `accentWords` — the
 * whole moment set at one size with the emphasis carried by colour — standing
 * alone: no other segment of the same moment may carry a role other than
 * `source`. The third clause is what makes the display-leading rule true by
 * construction rather than by trusting `lib/persian_moments.py`: with no
 * sibling blocks, the sibling-gap ceiling the block leading is tuned against
 * is not there, so the leading is set for reading instead.
 *
 * One shared helper feeds all three consequences — the three-line cap in
 * `maxLinesForRole` and the display leading and display weight in `tryHeroSize`
 * — so they can never diverge: a block that may run to three lines always gets
 * the leading those three lines were designed against and the weight that keeps
 * them from reading as slabs, and a block on tight leading never grows a third
 * line.
 *
 * Self-guarding on purpose: the upstream audit restricts `accentWords` to the
 * opening moment, but the fitter does not know positions in a timeline, so it
 * re-derives the flat fact from the segments in front of it.
 */
export function isFlatDisplayBlock(segments: readonly PersianSegment[]): boolean {
  const heroes = segments.filter((segment) => segment.role === "hero");
  if (heroes.length === 0) return false;
  if (!heroes.every((hero) => (hero.accentWords ?? []).length > 0)) return false;
  return segments.every(
    (segment) =>
      segment.role === "hero" ||
      segment.role === "source",
  );
}

/**
 * Whether a moment's segments form a claim+qualifier hook.
 *
 * A claim+qualifier hook is a `hero` carrying the claim in accent plus a `tail`
 * completing it in primary ink — the approved hook style — with no `accentWords`
 * anywhere: the colour comes from the roles, not from inline words. Like
 * `isFlatDisplayBlock` this derives the style from the segments in front of it,
 * because the fitter does not know positions in a timeline; the `kind: "hook"`
 * declaration (which the fitter receives as its required `kind` parameter) says
 * the moment gets the hook's tokens, and this predicate says *which* hook style.
 *
 * One shared helper feeds every claim+qualifier consequence — the ladder offset
 * in `fitMoment`, the tail size and weight in `tryHeroSize` — so the size, the
 * weight, and the starting rung can never disagree about which moments they
 * apply to. A `hero` plus a `tail` that is *not* declared a hook keeps the
 * ordinary lead-derived tail: the style is the structure *and* the declaration.
 */
export function isClaimQualifierHook(segments: readonly PersianSegment[]): boolean {
  const nonSource = segments.filter((segment) => segment.role !== "source");
  if (nonSource.length !== 2) return false;
  const [first, second] = nonSource;
  if (first.role !== "hero" || second.role !== "tail") return false;
  return segments.every((segment) => (segment.accentWords ?? []).length === 0);
}

/**
 * The tail size for a moment at a candidate hero size.
 *
 * A claim+qualifier hook's tail is `HOOK_TAIL_RATIO` of the hero — the 0.73 the
 * approved frame was measured at — while every other tail (and every lead) is
 * the ordinary `computeLeadPx` derivation. `claimQualifier` is the conjunction
 * of the declaration and the structure (`kind === "hook"` and
 * `isClaimQualifierHook`), computed once per fit: structure proposes, the
 * declaration disposes, and a hero-plus-tail that is not declared a hook keeps
 * the ordinary lead-derived tail. One helper so the size decision cannot drift
 * apart from the predicate that scopes it.
 */
export function tailPxForMoment(
  heroPx: number,
  leadPx: number,
  claimQualifier: boolean,
): number {
  if (claimQualifier) return Math.round(heroPx * HOOK_TAIL_RATIO);
  return leadPx;
}

/**
 * The gap between two role blocks for a moment at a candidate hero size.
 *
 * An ordinary moment's gap follows the lead (`computeStackGapPx`). A
 * claim+qualifier hook's gap follows the *qualifier* instead: the gap sits
 * between the claim and the qualifier, and at 68 × 0.55 = 37px it is the gap
 * the approved frame was measured at (37px of visible ink separation on the
 * still), while the lead derivation would give 36 × 0.55 = 20px — a denser
 * stack the approval never saw. The ratio is the same `STACK_GAP_RATIO` the
 * whole video uses; only the size it applies to is hook-scoped, so the rhythm
 * stays in the family while the hook keeps its approved air.
 *
 * Recorded alternative, not adopted: the reference the style was measured from
 * separates claim and qualifier by 0.635 × hero ≈ 59px at 93 — airier than the
 * approved 37px. The user approved the rendered c4 frame, so c4's 37 is the
 * spec; the 59 stays here as the measured number it was chosen against.
 */
export function stackGapPxForMoment(
  leadPx: number,
  tailPx: number,
  claimQualifier: boolean,
): number {
  if (claimQualifier) return Math.round(tailPx * STACK_GAP_RATIO);
  return computeStackGapPx(leadPx);
}

/**
 * The weight for a segment role inside a moment of a given shape.
 *
 * A claim+qualifier hook sets both its lines in Black — the hero keeps the
 * ordinary `ROLE_WEIGHT.hero`, the tail takes `HOOK_TAIL_WEIGHT` rather than
 * the ordinary `ROLE_WEIGHT.tail` — because the reference measures both lines
 * in the same weight class and the emphasis rides on colour. A flat display
 * hero keeps its scoped Bold. Everything else keeps `ROLE_WEIGHT`. One helper
 * so the three cases cannot drift apart the way a per-call-site ternary would.
 */
export function weightForRole(
  role: PersianSegmentRole,
  segments: readonly PersianSegment[],
  claimQualifier: boolean,
): EstedadWeight {
  if (claimQualifier && role === "tail") return HOOK_TAIL_WEIGHT;
  if (isFlatDisplayBlock(segments) && role === "hero") {
    return FLAT_DISPLAY_HERO_WEIGHT;
  }
  return ROLE_WEIGHT[role];
}

/**
 * The silhouette ratio of a fitted moment: narrowest painted line over widest.
 *
 * Measured across every line of every non-`source` segment — lines, not
 * segments, so a wrapped tail counts — on the `paintedWidthPerLine` basis,
 * which is what the component puts on screen (per-span advances, rendered word
 * gaps, and the ZWNJ paint charge). The bare ink advance would undercount a
 * ZWNJ-containing line by up to 0.53em per ZWNJ and call the approved frame
 * 0.58 against its painted 0.65; the gate must judge what the viewer sees. A
 * citation is excluded because it is appended to the phrase rather than part
 * of its shape. Exported so the node-fit bridge in
 * `tools/video/persian_compose.py` gates on the same number the fitter
 * produces, rather than re-deriving it.
 */
export function silhouetteRatio(fitted: FittedMoment): number {
  const widths: number[] = [];
  for (const segment of fitted.segments) {
    if (segment.role === "source") continue;
    for (const width of segment.paintedWidthPerLine) {
      if (width > 0) widths.push(width);
    }
  }
  // A line with no painted width contributes nothing; a moment with no painted
  // lines at all ratios 1 rather than dividing by zero.
  if (widths.length === 0) return 1;
  return Math.min(...widths) / Math.max(...widths);
}
/**
 * Lay out every segment at one candidate hero size, or return null if it does
 * not fit the height budget.
 *
 * Width never causes a null: `fitBlock` always finds *some* layout by adding a
 * line, and adding lines is what makes the stack too tall, so height is the one
 * budget that decides the rung. That is deliberate — it means the ladder search
 * is monotone (a smaller rung is never taller) and terminates on the first fit.
 */
function tryHeroSize(
  segments: readonly PersianSegment[],
  format: PersianFormat,
  heroPx: number,
  ladderIndex: number,
  heightBudgetPx: number,
  allowEscalation: boolean,
  kind: PersianMomentKind,
): FittedMoment | null {
  const leadPx = computeLeadPx(heroPx, format);
  const sourcePx = computeSourcePx(leadPx, format);
  const budgetPx = computeLineBudgetPx(format);
  // A flat display hero is the moment rather than a span inside it, so it is
  // allowed its third line, its display leading, and its display weight here —
  // one predicate for all three, so the line count, the leading, and the weight
  // can never disagree. A claim+qualifier hook likewise gets its qualifier size
  // and its Black tail weight here, via the shared `tailPxForMoment` and
  // `weightForRole` helpers rather than a per-call-site ternary. Both styles
  // are gated on the declaration *and* the structure: an undeclared
  // hero-plus-tail keeps the ordinary lead-derived tail, and an undeclared
  // accentWords hero keeps the ordinary two-line Black hero. Structure proposes,
  // the declaration disposes.
  const flatDisplay = kind === "hook" && isFlatDisplayBlock(segments);
  const claimQualifier = kind === "hook" && isClaimQualifierHook(segments);
  // The tail size and the inter-block gap are decided once per candidate rung
  // — the tail is the 0.73 qualifier on a claim+qualifier hook and the lead
  // derivation everywhere else, and the gap follows the qualifier on a hook —
  // so every segment at this rung agrees about both.
  const tailPx = tailPxForMoment(heroPx, leadPx, claimQualifier);
  const stackGapPx = stackGapPxForMoment(leadPx, tailPx, claimQualifier);

  const fitted: FittedSegment[] = [];
  let widest = 0;

  for (const segment of segments) {
    const fontSizePx = sizeForRole(segment.role, heroPx, leadPx, sourcePx, tailPx);
    const weight = weightForRole(segment.role, segments, claimQualifier);
    const maxLines = maxLinesForRole(segment.role, flatDisplay);

    let layout: LayoutResult;
    try {
      layout = fitBlock(segment.text, {
        maxWidthPx: budgetPx,
        wordGapRatio: TYPOGRAPHY[format].wordGapRatio,
        maxLines,
        // A rung change scales the whole moment coherently; a per-segment shrink
        // breaks the designed ratio between this segment and its siblings. So while
        // rungs remain, no escalation past `maxLines` is accepted — the search drops
        // a rung instead. The last rung allows it, because by then the alternative
        // is throwing.
        maxLinesEscalated: allowEscalation ? maxLines + 1 : maxLines,
        fontSizePx,
        weight,
      });
    } catch (error) {
      // At this rung the text does not fit its line count at any scale. While rungs
      // remain that is a rung answer, not an error: a smaller hero is exactly the
      // remedy, and rethrowing here would fail the render on the *largest* size
      // rather than trying the smaller ones. On the final rung `allowEscalation` is
      // true, so the throw propagates with its own diagnostic.
      if (!allowEscalation) return null;
      throw error;
    }

    if (!allowEscalation && layout.escalation !== "none") return null;

    const size = fontSizePx * layout.fontScale;
    const inkPerLine = layout.lines.map((line) =>
      measureInk(line.join(" "), size, weight),
    );
    // A flat display block reads as a three-line display sentence, so its
    // leading is the display leading — set for reading rather than against a
    // sibling gap that is not there. Everything else keeps the block leading.
    const lineGapPx = Math.round(
      size * (flatDisplay ? DISPLAY_LEADING_RATIO : BLOCK_LEADING_RATIO),
    );
    const inkHeight = inkPerLine.reduce(
      (total, ink) => total + ink.abovePx + ink.belowPx,
      0,
    );
    const heightPx = inkHeight + Math.max(0, inkPerLine.length - 1) * lineGapPx;
    // The rule width must match what the widest line *paints*, which — like the
    // fitter's width arithmetic — includes the rendered word gaps rather than
    // the font's space advances. `measureInk` returns the joined advance, so the
    // per-line width is re-derived through `measureWords` for consistency.
    // `measureWords` is also the paint proxy the silhouette gate reads: unlike
    // the ink advance it bills the ZWNJ .notdef advance Chromium charges per
    // word-span, so a ZWNJ-containing line is not undercounted by up to 0.53em.
    const gapRatio = TYPOGRAPHY[format].wordGapRatio;
    const paintedWidthPerLine = layout.lines.map((line, index) =>
      line.length <= 1 && line.length > 0
        ? Math.max(
            inkPerLine[index].widthPx,
            measureWords(line, size, weight, gapRatio),
          )
        : measureWords(line, size, weight, gapRatio),
    );
    const widthPx = layout.lines.reduce(
      (max, line, index) =>
        Math.max(
          max,
          line.length <= 1
            ? inkPerLine[index].widthPx
            : measureWords(line, size, weight, gapRatio),
        ),
      0,
    );
    widest = Math.max(widest, widthPx);

    fitted.push({
      role: segment.role,
      text: segment.text,
      revealAfterSeconds: segment.revealAfterSeconds ?? 0,
      fontSizePx: size,
      weight,
      lines: layout.lines,
      lineGapPx,
      inkPerLine,
      paintedWidthPerLine,
      heightPx,
      widthPx,
      escalation: layout.escalation,
      accentWords: segment.accentWords ?? [],
    });
  }

  const stackHeight =
    MOMENT_RULE_HEIGHT_PX +
    stackGapPx +
    fitted.reduce((total, segment) => total + segment.heightPx, 0) +
    Math.max(0, fitted.length - 1) * stackGapPx;

  if (stackHeight > heightBudgetPx) return null;

  return {
    heroPx,
    leadPx,
    sourcePx,
    stackGapPx,
    segments: fitted,
    heightPx: stackHeight,
    widthPx: widest,
    ladderIndex,
    presenceLiftPx: 0,
  };
}

/**
 * Presence lift for short heroes — the ink-mass correction.
 *
 * The ladder picks one rung for the whole moment, so with the compressed
 * ladder every moment lands on rung 0 at the same em size while painting
 * wildly different ink widths (241px vs 593px). The eye reads that as
 * "m1 looks small" even though the px match. The lift walks the hero up
 * while the stack stays narrow and short, re-running the same `tryHeroSize`
 * machinery so height and escalation safety come free.
 *
 * Gates, all required: every hero segment is single-line, each hero is at
 * most `SHORT_HERO_MAX_CHARS` visible chars, every segment's escalation is
 * `none`, and the fitted width fills less than `SHORT_HERO_FILL_FRACTION`
 * of the line budget. Then iterate `heroPx × PRESENCE_LIFT_STEP` capped at
 * `computeShortHeroMaxPx`, keeping the last fit that still lays out clean.
 * Each step re-checks the fill: a mid-width stack stops once it reaches the
 * fill fraction (continuity), while a micro stack never reaches it and runs
 * to the cap (which dominates micro cases — «قهوه» would need ~360px to
 * fill 0.72, so pure fit-to-width is wrong). Height safety comes free from
 * `tryHeroSize` returning null past the height budget.
 *
 * Measuring-text rule compliance: the re-layout goes through real
 * measurement post-font-load (the caller already awaited `estedadReady`),
 * and the cap mirrors the fitText-cap pattern — measure, then cap the fit.
 */
function presenceLiftFit(
  base: FittedMoment,
  segments: readonly PersianSegment[],
  format: PersianFormat,
  heightBudgetPx: number,
  kind: PersianMomentKind,
): FittedMoment {
  // Hooks never lift: their presence was already set by the ladder offset
  // (`HOOK_HERO_LADDER_OFFSET` / `FLAT_HERO_LADDER_OFFSET`), which balances the
  // hook's total ink mass against the single-line heroes. Lifting a short hook
  // hero back up would reintroduce the dominance the offset removes — a narrow
  // hook at the cap is a poster, not an opening.
  if (kind === "hook") return base;
  const heroes = base.segments.filter((s) => s.role === "hero");
  if (heroes.length === 0) return base;
  for (const hero of heroes) {
    if (hero.lines.length !== 1) return base;
    if (visibleLength(hero.text) > SHORT_HERO_MAX_CHARS) return base;
  }
  for (const segment of base.segments) {
    if (segment.escalation !== "none") return base;
  }
  const budgetPx = computeLineBudgetPx(format);
  if (base.widthPx >= SHORT_HERO_FILL_FRACTION * budgetPx) return base;

  const capPx = computeShortHeroMaxPx(format);
  if (base.heroPx >= capPx) return base;

  const fillPx = SHORT_HERO_FILL_FRACTION * budgetPx;
  let best: FittedMoment = base;
  let candidate = base.heroPx;
  for (;;) {
    const next = Math.min(Math.round(candidate * PRESENCE_LIFT_STEP), capPx);
    if (next <= candidate) break;
    const fit = tryHeroSize(segments, format, next, base.ladderIndex, heightBudgetPx, false, kind);
    if (!fit) break;
    best = { ...fit, presenceLiftPx: fit.heroPx - base.heroPx };
    // Mid widths stop once they carry their weight; micro widths never reach
    // the fill and run to the cap. Either way the stack never exceeds the
    // height budget — `tryHeroSize` returns null past it.
    if (fit.widthPx >= fillPx) break;
    if (next >= capPx) break;
    candidate = next;
  }
  return best;
}

/**
 * Choose one size for a moment and lay out all of its segments at it.
 *
 * Walks `HERO_LADDER_PX` from the largest rung down and returns the first rung
 * whose whole stack fits the height budget with no segment escalating — except
 * that a flat display block starts its walk `FLAT_HERO_LADDER_OFFSET` rungs
 * below the top (so the three-line hook lands one rung down), and a
 * claim+qualifier hook starts `HOOK_HERO_LADDER_OFFSET` rungs down (the 0.73
 * qualifier adds enough ink mass that the hero steps two rungs while the hook
 * still out-presences the single-line heroes elsewhere). Every other moment
 * still starts at rung 0. If no rung
 * qualifies, the smallest rung is retried with escalation allowed, so a
 * pathological but authored moment still renders rather than failing the video.
 *
 * `kind` is required — not optional with a default — so a caller that forgets
 * to state it is a compile error rather than a silently ordinary-looking hook.
 * The kind switches the hook-scoped tokens on; the style inside a hook still
 * derives from the segments (`isClaimQualifierHook` vs `isFlatDisplayBlock`),
 * because the fitter lays out the structure in front of it. A hero-plus-tail
 * structure that is *not* declared a hook keeps the ordinary lead-derived tail:
 * structure proposes, the declaration disposes.
 *
 * Throws only when even that fails, which means the content is wrong rather than
 * the layout: `lib/persian_moments.py` refuses over-long segments before a render
 * starts, so reaching this throw means props were assembled outside the pipeline.
 */
export function fitMoment(
  segments: readonly PersianSegment[],
  format: PersianFormat,
  kind: PersianMomentKind,
): FittedMoment {
  if (segments.length === 0) {
    throw new Error(
      "fitMoment() received no segments. A moment is one Persian phrase carried " +
        "by an ordered segment list; an empty list is a props-assembly fault.",
    );
  }

  const ladder = HERO_LADDER_PX[format];
  const heightBudgetPx = computeMaxStackPx(format);

  // Hook styles begin their walk below the top: three lines (flat) or a large
  // qualifier (claim+qualifier) carry multiples of a single-line hero's ink
  // mass, so the hook balances its total presence below the top instead of
  // matching em size. An ordinary moment — whatever its kind — starts at 0.
  const hookWalk = isClaimQualifierHook(segments)
    ? HOOK_HERO_LADDER_OFFSET
    : FLAT_HERO_LADDER_OFFSET;
  const startIndex = kind === "hook" ? hookWalk : 0;
  for (let index = startIndex; index < ladder.length; index += 1) {
    const heroPx = ladder[index];
    const fit = tryHeroSize(segments, format, heroPx, index, heightBudgetPx, false, kind);
    if (fit) return presenceLiftFit(fit, segments, format, heightBudgetPx, kind);
  }

  const last = ladder.length - 1;
  const fallback = tryHeroSize(
    segments,
    format,
    ladder[last],
    last,
    heightBudgetPx,
    true,
    kind,
  );
  if (fallback) return fallback;

  const summary = segments
    .map((segment) => `${segment.role}:${segment.text.slice(0, 24)}`)
    .join(" | ");
  throw new Error(
    `Persian moment does not fit even at the smallest hero rung (${ladder[last]}px) ` +
      `within ${Math.round(heightBudgetPx)}px of height. The moment is carrying too ` +
      `much text: split it into two moments, or shorten the lead. ` +
      `Segments: ${summary}`,
  );
}

/**
 * Margins that collapse one text row onto its measured ink.
 *
 * With `line-height` equal to the font's own line box, the row is
 * `(ascent+descent)·size` tall and the baseline sits `ascent·size` below its top.
 * Subtracting the unused ascent above and the unused descent below leaves a box
 * exactly as tall as the painted glyphs, which is what makes a declared gap the
 * gap that appears.
 *
 * Both values are non-positive by construction, since no glyph exceeds the font's
 * own metrics; they are clamped anyway, because a fallback ink measurement (see
 * `measureInk`) legitimately returns the font box and would otherwise produce a
 * positive margin that adds space instead of removing it.
 */
export function inkTrimMargins(
  ink: InkBox,
  fontSizePx: number,
  fontAscentEm: number,
  fontDescentEm: number,
): { readonly marginTopPx: number; readonly marginBottomPx: number } {
  const ascentPx = fontAscentEm * fontSizePx;
  const descentPx = fontDescentEm * fontSizePx;
  return {
    marginTopPx: -Math.max(0, ascentPx - ink.abovePx),
    marginBottomPx: -Math.max(0, descentPx - ink.belowPx),
  };
}
