/**
 * Design tokens for the Persian composition.
 *
 * Two format targets share one token set: vertical 1080×1920 (the default) and
 * landscape 1920×1080 (long-form YouTube). Sizes are expressed per format rather
 * than as one scale with a multiplier, because the binding constraint differs in
 * kind. Vertical is *width*-bound: a phone screen forces large type or nothing is
 * readable at arm's length. Landscape is *distance*-bound: the same physical text
 * is read from further away on a bigger screen, so it needs proportionally less of
 * the frame.
 *
 * ## What this token set is for
 *
 * The composition paints **moments**, not a caption track. A moment is one
 * deliberate typographic event that occupies the frame for a few seconds and then
 * leaves it empty. Most of the running time carries no text at all.
 *
 * ## The one structural rule
 *
 * A moment is **one grammatical Persian phrase with one emphasised span inside
 * it** — never a heap of detached fragments. The predecessor of this file
 * described four independent slots (`kicker` above, hero in the middle, `unit`
 * beside it, `label` below) and every slot had its own size, its own colour, and
 * its own alignment. What reached the screen was:
 *
 *     ۲۲۶۴            ← 260px accent numeral, right-anchored
 *              نفر     ← 44px, at the numeral's baseline, far to its left
 *     دانشگاه اولو، فنلاند   ← 44px, below, right-anchored
 *
 * Three sizes, three different left edges, and no sentence anywhere: a reader
 * could not tell what 2264 counted, whether the university was the subject or the
 * source, or that a study was being described at all. The information was present
 * and the grammar was missing, which is not a styling defect — it is the layout
 * asserting relationships the language never stated.
 *
 * So slots are gone. A moment now carries an ordered list of **segments**, each
 * with a role (`lead`, `hero`, `tail`, `source`), and the roles compose one
 * phrase read top to bottom:
 *
 *     مطالعهٔ دانشگاه اولوی فنلاند روی      ← lead
 *     ۲۲۶۴ نفر                              ← hero (the emphasis)
 *
 * Two sizes, one right edge, one sentence. The unit lives inside the hero span
 * because «۲۲۶۴ نفر» is how the quantity is *said*, and splitting a spoken phrase
 * across two type sizes is what produced the floating «نفر».
 *
 * ## Why sizes are derived per moment rather than fixed per kind
 *
 * The predecessor fixed `statementPx: 80`, `figurePx: 260`, `kickerPx: 38`. Those
 * numbers were each defensible alone and wrong together: an 80px claim under a
 * 38px accent line is a 2.1:1 ratio that reads as a caption with a label, while a
 * 260px numeral over a 44px line is 5.9:1 and reads as two unrelated objects. The
 * ratio, not the absolute size, is what the eye judges.
 *
 * So one size is chosen per moment — the largest rung of `HERO_LADDER_PX` at which
 * the whole composed stack still fits its width budget and its height budget — and
 * every other role derives from it by a fixed ratio. A short numeral therefore
 * lands on a big rung and a two-line claim lands on a smaller one, and in both
 * cases the lead sits at the same proportion of the hero. Proportion is designed;
 * absolute size is measured.
 *
 * ## Why the vertical rhythm is measured ink, not line boxes
 *
 * Estedad's natural line box is 1.665em, and a numeral's real ink is about 0.97em
 * tall. Laying such a line out at any fixed `line-height` therefore leaves leading
 * that has nothing to do with the glyphs in it: the shipped render put 133px of
 * empty space between a 260px numeral and the line beneath it, against a designed
 * gap of 26px, entirely from half-leading nobody asked for. That gap is not
 * tunable by choosing a better multiplier, because the slack depends on which
 * glyphs are in the string — an ascender-free numeral and a line of «مسئله» differ
 * by a third of an em.
 *
 * The fix is to measure each laid-out line's real ink box on canvas
 * (`measureInk`) and trim the row to it with negative margins. Then a gap declared
 * as 34px is 34px of visible space, for every string, at every size. The constants
 * below are what that arithmetic needs, and each was measured against the vendored
 * files rather than assumed:
 *
 * | Quantity | Value | How |
 * |---|---|---|
 * | font ascent | 1.075em | `PIL.ImageFont.getmetrics()`, all three weights |
 * | font descent | 0.590em | same |
 * | natural line box | 1.665em | ascent + descent |
 * | worst real ink above baseline | 0.98em | bbox over a Persian corpus incl. «أ», «الله» |
 * | worst real ink below baseline | 0.42em | bbox, worst is a final «ی» |
 *
 * `tests/contracts/test_persian_font_metrics.py` re-measures the files and fails
 * if these drift, so the trimming arithmetic cannot quietly go wrong when a font
 * is revendored.
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
 * Deliberately narrow: footage supplies the colour, and the typographic layer
 * stays close to monochrome so it reads over any clip.
 *
 * ## Why the ink is not pure white and the accent is not chroma yellow
 *
 * `#FFFFFF` over footage plus a high-chroma yellow accent is the visual signature
 * of automated short-form captioning. It is not wrong in any measurable sense —
 * both clear every contrast threshold — but it is *recognisable*, and looking
 * machine-made was the complaint this palette answers.
 *
 * A warm off-white reads as printed ink rather than as an overlay, and an amber
 * accent sits in the same temperature family as the off-white instead of
 * puncturing it. Amber costs contrast — 5.75:1 against the worst case where
 * chroma yellow scores 7.9:1 — and that cost is affordable because the scrim
 * below guarantees the background, so the accent never has to survive raw
 * footage on its own.
 *
 * ## Which role gets the accent
 *
 * The `hero` segment, and nothing else. `lead` and `tail` are primary ink, at
 * full strength — they are part of the same sentence, not a caption on it. The
 * predecessor put the accent on the small `kicker` line above a plain-ink claim,
 * which inverted the hierarchy: the eye went to a 38px scoping phrase and had to
 * work back up to the 80px point of the frame.
 */
export const PERSIAN_PALETTE = {
  /** Primary ink. Warm off-white: reads as printed, not as an overlay. */
  ink: "#F7F5F2",
  /** Supporting ink — the source line only. One step down, same family. */
  inkSecondary: "#D6D0C6",
  /** The single accent. The `hero` segment of a moment, never anything else. */
  accent: "#FFC24B",
  /** Rule and divider colour, at low alpha over the scrim. */
  rule: "rgba(247, 245, 242, 0.22)",
  /** Watermark glow, as an "R, G, B" triplet for rgba() interpolation. */
  watermarkGlowRgb: "255, 194, 75",
  /** Background for a moment with no footage behind it. */
  voidBackground: "#0B0B0C",
} as const;

/**
 * Scrim behind a moment.
 *
 * A gradient wash rather than a panel. The panel it replaces was the right answer
 * for captions — a bounded box that establishes local contrast for a line that is
 * always on screen — and the wrong answer for moments, because a rounded
 * rectangle around a figure reads as a UI element rather than as a composition.
 *
 * ## Why the peak alpha is 0.72
 *
 * The worst case is fully clipped white footage, luminance 255. Composited under
 * alpha α, that becomes 255(1−α), and the ink must still clear WCAG AA for body
 * text (4.5:1) rather than merely large text (3:1) — a moment is read once and
 * briefly, so it gets the stricter threshold, not the looser one.
 *
 * | α | worst-case bg | ink | secondary | accent |
 * |---|---|---|---|---|
 * | 0.55 | 114.7 | 4.37 | 3.10 | 2.96 |
 * | 0.62 | 96.9 | 5.70 | 4.05 | 3.86 |
 * | 0.72 | 71.4 | 8.48 | 6.02 | 5.75 |
 * | 0.82 | 45.9 | 12.50 | 8.87 | 8.46 |
 *
 * 0.72 is the lowest value at which *all three* inks clear 4.5:1, which matters
 * because the accent is the one carrying the hero. 0.82 would buy margin nobody
 * needs at the cost of visibly greying the footage.
 *
 * ## Why it is a gradient and not a flat fill
 *
 * A flat 0.72 over the whole frame darkens the clip into a backdrop, which
 * defeats the point of sourcing footage. The wash peaks behind the text and
 * reaches zero before the frame edge, so the corners of every shot stay at full
 * exposure. `peakAlpha` is therefore the alpha directly behind the glyphs — the
 * only place the contrast arithmetic above has to hold.
 */
export const SCRIM = {
  /** Alpha directly behind the text. The contrast floor is computed here. */
  peakAlpha: 0.72,
  /**
   * Fraction of the frame's shorter axis over which the wash falls from
   * `peakAlpha` to zero, measured from the edge of the moment's own ink.
   */
  falloffFraction: 0.28,
  /** Frames the scrim takes to arrive and to leave, independent of the text. */
  fadeFrames: 10,
} as const;

// ---------------------------------------------------------------------------
// Font metrics — measured, not assumed
// ---------------------------------------------------------------------------

/** Estedad's ascent, as a multiple of the em. Identical across all three weights. */
export const FONT_ASCENT_EM = 1.075;

/** Estedad's descent, as a multiple of the em. */
export const FONT_DESCENT_EM = 0.59;

/** Natural line box — what the browser uses at `line-height: normal`. */
export const FONT_LINE_BOX_EM = FONT_ASCENT_EM + FONT_DESCENT_EM;

/**
 * Worst real ink above the baseline over a Persian corpus, as a multiple of the
 * em. Includes the outliers a script can legitimately contain — hamza above alef,
 * the «الله» ligature — not just typical text, because a zone computed from
 * typical text clips the atypical line.
 */
export const INK_ABOVE_EM = 0.98;

/** Worst real ink below the baseline. Worst case is a word-final «ی». */
export const INK_BELOW_EM = 0.42;

/**
 * Worst total real ink height of one line, as a multiple of the em.
 *
 * The upper bound used for height budgeting when a real measurement is not
 * available yet (the ladder search runs before any line exists). The painted
 * rhythm uses per-line measured ink instead — see `measureInk`.
 */
export const INK_HEIGHT_EM = INK_ABOVE_EM + INK_BELOW_EM;

/**
 * `line-height` applied to every text row, as a multiplier.
 *
 * Set to the font's own line box, which makes the CSS half-leading exactly zero
 * and puts the baseline exactly `FONT_ASCENT_EM` below the top of the row. That is
 * the property the trimming arithmetic needs: with a known baseline position and a
 * measured ink box, the negative margins that collapse a row onto its ink are
 * `-(ascent − inkAbove)` and `-(descent − inkBelow)`, both guaranteed non-positive
 * because no glyph exceeds the font's own metrics.
 *
 * Choosing a tighter multiplier for looks would make half-leading negative, push
 * the baseline up, and leave the glyphs painting outside their own row box — which
 * happens to work in Chrome and is one clipped renderer away from silently eating
 * the top of every line. Looks are set by the *gap* tokens, which now describe
 * real ink separation; this value is pure arithmetic.
 */
export const ROW_LINE_HEIGHT = FONT_LINE_BOX_EM;

// ---------------------------------------------------------------------------
// The size system
// ---------------------------------------------------------------------------

/**
 * Hero size ladder, largest first.
 *
 * The fitter walks it and takes the first rung whose composed stack fits both
 * budgets. Rungs step by roughly 1.21× — close enough that consecutive moments
 * do not read as a size change when they land on neighbouring rungs, far enough
 * apart that the search terminates in a handful of measurements.
 *
 * The top rung is the size at which a four-digit Persian numeral spans a little
 * over half the frame width, which is where a quantity stops reading as "large
 * text" and starts reading as the subject of the frame. The bottom rung is the
 * smallest size at which a two-line Persian claim is still comfortable at arm's
 * length on a phone; below it the moment should have been split in two rather
 * than shrunk, so the fitter throws instead of continuing down.
 */
export const HERO_LADDER_PX: Record<PersianFormat, readonly number[]> = {
  vertical:  [123, 110, 93, 80, 69, 59],
  landscape: [200, 168, 140, 118, 98, 82],
};

/**
 * Rungs a flat display hero skips below the ladder top before it starts walking.
 *
 * One. A flat display hook is three lines, so at the same rung it carries roughly
 * three times the ink mass of the single-line heroes it sits among. Stepping one
 * rung down balances the hook's *total presence* against theirs instead of
 * matching its em size to theirs, and it buys the width slack that lets the three
 * lines breathe (fills drop from .76/.78/.88 at 123 to .68/.69/.78 at 110, spread
 * 0.12 → 0.10).
 *
 * An offset, not a second ladder and not a literal: the hook keeps following the
 * ladder if the ladder ever moves. `fitMoment` starts the flat walk here; every
 * other moment still starts at rung 0.
 */
export const FLAT_HERO_LADDER_OFFSET = 1;

/**
 * Rungs a claim+qualifier hook skips below the ladder top before it starts walking.
 *
 * Two — rung 93 of `[123, 110, 93, 80, 69, 59]`. The approved hook style sets the
 * claim (`hero`) in accent and completes it with a qualifier (`tail`) in primary
 * ink at nearly three-quarters of the hero's size, so the moment carries
 * substantially more ink mass than any single-line hero it sits among; matching
 * em size with the ordinary heroes would make the opening frame dominate the
 * video rather than open it. The reference the style was measured from implies a
 * 96.7px hero in 1080-wide space, which lands nearest rung 2 (Δ3.7 against rung
 * 93, Δ13.3 against rung 1 at 110) — the ladder has no rung at the implied size,
 * so the search starts where the reference points and walks down from there.
 *
 * The flat style keeps its own offset of 1: two hook styles, two offsets, each
 * with its own measured reason — the flat hook's three equal lines against this
 * style's large qualifier. `fitMoment` starts the claim+qualifier walk here;
 * every ordinary moment still starts at rung 0.
 */
export const HOOK_HERO_LADDER_OFFSET = 2;

/**
 * Presence lift for short heroes — the ink-mass correction.
 *
 * The eye judges ink mass, not em size. With the compressed ladder every
 * ordinary moment lands on rung 0 at the same size, so a micro hero («قهوه» — 241px
 * in an 881px column) reads tiny beside a normal one (593px) at the
 * identical 123px. The old ladder hid this via spread (short → big rung);
 * the compressed ladder needs an explicit lift.
 *
 * Pure fit-to-width is wrong for micro words: «قهوه» would need ~360px to
 * fill the column, which is poster type, not emphasis. So the lift walks
 * gradually (`PRESENCE_LIFT_STEP`) and the cap dominates micro cases while
 * the walk preserves continuity for mid widths. The cap mirrors the
 * fitText-cap pattern from the measuring-text rule: measure post-font-load,
 * cap the fit.
 */
export const SHORT_HERO_MAX_CHARS = 12;

/** Fill fraction below which a short-hero stack qualifies for the lift. */
export const SHORT_HERO_FILL_FRACTION = 0.72;

/** Gradual walk per lift step — continuity for mid widths, not a jump. */
export const PRESENCE_LIFT_STEP = 1.12;

/**
 * Cap on the lifted hero, as a multiple of the format's own ladder top.
 *
 * A ratio, not two literals: vertical's 123px × 1.4 ≈ 172px, landscape's
 * 200px × 1.4 = 280px. Both formats get the same presence headroom above
 * their own top rung without restating the number per format.
 */
export const SHORT_HERO_MAX_RATIO = 1.4;

/** Cap on the lifted hero for a format, in px. Derived, never authored. */
export function computeShortHeroMaxPx(format: PersianFormat): number {
  return Math.round(HERO_LADDER_PX[format][0] * SHORT_HERO_MAX_RATIO);
}

/**
 * Lines the hero may occupy.
 *
 * Two. A hero broken across two lines is still one block — one size, one colour,
 * one right edge — so it stays one phrase; that is ordinary typesetting, and
 * `fitBlock` applies the Persian break rules to it like any other block.
 *
 * Forcing it to one line was tried and is worse. The ladder then has to shrink a
 * long hero until it fits a single line: «خطِ فارسی را رها نکن» drops toward the
 * bottom rung, where the lead beside it has already hit the 32px floor and the
 * emphasis has all but disappeared. That is the «خط نارنجی بیش از حد کوچیکه»
 * complaint, reintroduced by a rule meant to protect the phrase.
 *
 * What must not happen is a *spoken* unit split across two type sizes — the
 * floating «نفر» — and that is prevented by the unit living inside the hero text,
 * not by a line limit.
 */
export const HERO_MAX_LINES = 2;

/**
 * Lines a flat display hero may occupy.
 *
 * Three. A flat display hero — a `hero` segment that carries `accentWords`,
 * the whole moment set at one size with the emphasis carried by colour — is a
 * whole sentence rather than a sized emphasis span, so it is typeset as a
 * display block rather than as an emphasis span.
 *
 * `HERO_MAX_LINES = 2` exists to protect a *sized* emphasis: a hero that
 * shrinks until it fits fewer lines loses its size advantage over the lead
 * beside it. A flat hero has no size advantage to protect — everything is one
 * size already — so the two-line cap did the opposite of its job. The shipped
 * hook («می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟», 34 visible chars) was
 * pinned by it to the bottom of the ladder at 69px, the smallest hero in a
 * video whose other moments run 123–172px, and at 69px the only legal two-line
 * splits are 774.57/434.04 (spread 0.39, the shipped one) and 376.28/832.33
 * (spread 0.52): the breaker had already picked the better of the two. With
 * three lines allowed the same sentence has exactly one legal split —
 * `می‌دونی قهوه` / `با هورمون‌هات` / `چی‌کار می‌کنه؟` — painted one rung down
 * at 110px as 598.97 / 610.14 / 690.05 (fills .68/.69/.78, spread 0.10).
 *
 * Three, not four: at 155px the only legal four-line split is 2-2-1-1 with
 * spread 0.49, which brings the rag straight back. The third line is what
 * rescues the hook; the fourth is what re-breaks it.
 *
 * Why the size stops one rung below the ladder top instead of lifting further:
 * at 138px the same sentence also fits three lines (painted 751.56 / 765.58 /
 * 866.07), and lifting it there was rejected on evidence rather than taste.
 * At 866px the longest line fills .98 of the budget, and with the paint drift
 * `FIT_SPAN_DRIFT_FRACTION` charges, its painted ink lands a few px outside
 * the left edge of the column `computeMomentColumns` defines — the
 * `INK_OVERSHOOT` condition the frame verifier flags on a correct fitter.
 * The offset rung is therefore the size, not a starting offer: a later change
 * that "improves" the hook by lifting it reintroduces the overshoot the
 * three-line cap was measured to avoid.
 *
 * Scoped by `isFlatDisplayBlock` in `layout.ts` to exactly the flat case — a
 * `hero` with a non-empty `accentWords` list and no sibling segment of any
 * role other than `source` — so every ordinary hero keeps the two-line cap.
 */
export const FLAT_HERO_MAX_LINES = 3;

/** Lines a `lead` or `tail` segment may occupy. */
export const MAX_LEAD_LINES = 2;

/**
 * Role proportions, relative to the chosen hero size.
 *
 * `lead` at 0.38 of the hero is the ratio at which the two read as one phrase
 * with an emphasis rather than as a heading over a subheading. Below about 0.3
 * the lead becomes a caption on the hero; above about 0.55 the emphasis stops
 * being an emphasis. The clamps matter more than the ratio: on the vertical top
 * rung 0.38 × 123 = 47px, which stands on its own, and on the bottom rung
 * 0.38 × 59 = 23px, which is below the size a phone can carry — so the 32px
 * floor binds there and the lead arrives at 32px (see `computeLeadPx`).
 */
export const LEAD_RATIO = 0.382;

/** Ceiling on the lead, as a fraction of the hero. Keeps the emphasis legible. */
export const LEAD_MAX_RATIO = 0.55;

/**
 * Size of a hook's qualifier (`tail`), as a fraction of the hook's hero.
 *
 * 0.73, deliberately above `LEAD_MAX_RATIO = 0.55` — and the ceiling does not
 * bind here because it was written for a different design. The ceiling answers
 * "above what fraction does a supporting line stop being an emphasis": in an
 * ordinary moment the emphasis is carried by *size*, so a lead past about 0.55
 * competes with the hero it supports. In a claim+qualifier hook the emphasis is
 * carried by *colour* — accent orange against primary ink — so the qualifier can
 * be nearly as large without competing: the eye never mistakes which line is the
 * claim, because they are different colours. The approved frame sets the tail at
 * 68px against a 93px hero (0.73), and the reference it was measured from sits at
 * the same 0.73 of its implied 96.7px hero.
 *
 * Scoped to hooks (`isClaimQualifierHook` in `layout.ts` decides where it
 * applies), so ordinary moments keep their ceiling. Raising `LEAD_MAX_RATIO`
 * itself would let every lead in the video grow until no hero is an emphasis.
 */
export const HOOK_TAIL_RATIO = 0.73;

/**
 * Weight of a hook's qualifier (`tail`).
 *
 * 900 (Black), against `ROLE_WEIGHT.tail = 500`. In the reference both lines
 * measure the same weight class — stroke-run medians 0.20em on the claim and
 * 0.22em on the qualifier, each of its own size — so a Medium qualifier under a
 * Black claim would be a weight step the reference never takes. And the step is
 * safe to take independently of the fit: Estedad's Persian advance widths are
 * identical across 500/700/900 (only Latin widens), so the weight changes ink
 * mass and roughly 10px of block height per step, and changes neither the ladder
 * rung nor the line break — the same property the flat display weight's comment
 * in `layout.ts` records. The claim keeps the ordinary `ROLE_WEIGHT.hero = 900`
 * with no new token: it is the same emphasis at the same weight, only smaller.
 */
export const HOOK_TAIL_WEIGHT: 900 = 900;

/**
 * Silhouette band a hook's lines must read inside.
 *
 * The silhouette ratio is the narrowest painted line width divided by the
 * widest, across every line of every non-`source` segment — lines, not
 * segments, so a wrapped tail counts. It is the single number that separates a
 * designed hook from a typeset one: the rejected flat arrangement measured 0.88
 * (two lines of nearly equal width read as a rectangle), while the reference
 * measures 0.62 (a step) and the approved c4 frame 0.647. A hook at the 0.55
 * ceiling measured 0.489 — a qualifier so narrow it reads as a caption under a
 * poster. The band 0.52–0.78 passes the reference and c4 with margin on both
 * sides and refuses both the 0.88 rectangle and the 0.489 sliver; round numbers,
 * chosen so a future re-measurement that moves a hundredth changes nothing.
 *
 * What this does to the flat style, stated plainly: the flat line breaker
 * minimises squared slack, which *balances* lines, so a flat hook measures
 * around 0.87–0.88 and fails this gate. That is a true finding about the flat
 * style, not a calibration problem in the band: a balanced three-line block is
 * a rectangle by construction, and the gate refuses rectangles. The flat style
 * would need a hook-specific break objective — one that prefers a stepped
 * silhouette over balanced slack — before it could pass. The band stays.
 */
export const HOOK_SILHOUETTE_MIN_RATIO = 0.52;

/** Upper bound of the hook silhouette band — see `HOOK_SILHOUETTE_MIN_RATIO`. */
export const HOOK_SILHOUETTE_MAX_RATIO = 0.78;

/**
 * Stagger between a hook's claim and its qualifier, in frames at 30fps.
 *
 * 9 frames ≈ 0.3s — the rhythm a person speaks the sentence in: the claim
 * lands, then the qualifier completes it. The ordinary inter-segment stagger is
 * 5 frames (0.167s), a mild beat between supporting lines; a hook's two lines
 * are two beats of one sentence, so the beat is longer. Both lines arrive as one
 * mass each (no word-by-word stagger): a claim staggered letter-group by
 * letter-group stops reading as a claim. Measured example, one project: with a
 * 13-frame entrance the qualifier settled at frame 22 of a 4.2s opening moment —
 * that duration was the project's moment length, not a hook-window token.
 */
export const HOOK_SEGMENT_STAGGER_FRAMES = 9;

/** The source line, as a fraction of the lead. Smallest type in the system. */
export const SOURCE_RATIO = 0.62;

/**
 * Gap between two role blocks, as a fraction of the lead size.
 *
 * Expressed against the lead rather than the hero so the rhythm of a moment does
 * not balloon on the top rung: a gap proportional to a 260px numeral would be
 * larger than the lead line it separates.
 *
 * This is a gap between *measured ink boxes*, so it is what actually appears.
 */
export const STACK_GAP_RATIO = 0.55;

/** Leading between lines *inside* one block, as a fraction of that block's size. */
export const BLOCK_LEADING_RATIO = 0.16;

/**
 * Leading between the lines of a flat display block, as a fraction of its size.
 *
 * 0.382. `BLOCK_LEADING_RATIO = 0.16` is tuned for a block whose siblings sit
 * `computeStackGapPx` away — about 0.21 em of the hero — and it must stay
 * under that sibling gap, or the lines of one block would separate more than
 * two blocks do. A flat display hero has no siblings: it *is* the moment, so
 * its leading is set for reading a three-line display sentence instead of
 * against a gap that is not there.
 *
 * Measured at 110px on the shipped hook's winning 2-2-2 split, against the
 * block leading it replaces:
 *
 * | ratio | gap | baseline-to-baseline, per pair |
 * |---|---|---|
 * | 0.16 | 18px | 1.09 / 1.16 em |
 * | 0.382 | 42px | 1.31 / 1.38 em |
 *
 * At 69px the old 0.16 yielded 11px of visible ink separation — the cramped
 * look the hook was rejected for. At 0.382 the three display lines breathe
 * without drifting apart: the gap stays well under any sibling gap that could
 * exist beside it, and the sibling-gap ceiling does not bind here precisely
 * because there are no siblings to confuse the lines with.
 *
 * Scoped the same way as `FLAT_HERO_MAX_LINES` — `isFlatDisplayBlock` in
 * `layout.ts` — so every ordinary block keeps the tighter leading.
 */
export const DISPLAY_LEADING_RATIO = 0.382;

export interface FormatTypography {
  /** Floor on the lead size, px. Below this a phone cannot carry the line. */
  readonly leadMinPx: number;
  /** Floor on the source line, px. */
  readonly sourceMinPx: number;
  /** Horizontal gap between words, as a fraction of the block's own size. */
  readonly wordGapRatio: number;
  /** Watermark size, px. */
  readonly watermarkFontSizePx: number;
  /**
   * Fraction of the usable frame height one moment's stack may fill.
   *
   * A moment that fills the whole usable frame is a wall of text whatever its
   * type sizes are, and this is the only budget that stops the ladder from
   * choosing a huge rung for a long phrase and letting it run off the frame.
   */
  readonly maxStackFraction: number;
}

export const TYPOGRAPHY: Record<PersianFormat, FormatTypography> = {
  vertical: {
    leadMinPx: 32,
    sourceMinPx: 30,
    wordGapRatio: 0.22,
    watermarkFontSizePx: 24,
    maxStackFraction: 0.58,
  },
  landscape: {
    leadMinPx: 44,
    sourceMinPx: 26,
    wordGapRatio: 0.2,
    watermarkFontSizePx: 26,
    // Landscape has 1080px of height against vertical's 1920 and no platform
    // chrome to avoid, so the same fraction would put type edge to edge.
    maxStackFraction: 0.62,
  },
};

/** The lead size for a given hero size, in px. Derived, never authored. */
export function computeLeadPx(heroPx: number, format: PersianFormat): number {
  const t = TYPOGRAPHY[format];
  const ideal = heroPx * LEAD_RATIO;
  const ceiling = heroPx * LEAD_MAX_RATIO;
  return Math.round(Math.min(Math.max(ideal, t.leadMinPx), Math.max(ceiling, t.leadMinPx)));
}

/** The source size for a given lead size, in px. */
export function computeSourcePx(leadPx: number, format: PersianFormat): number {
  return Math.round(Math.max(leadPx * SOURCE_RATIO, TYPOGRAPHY[format].sourceMinPx));
}

/** Gap between two role blocks, in px, for a given lead size. */
export function computeStackGapPx(leadPx: number): number {
  return Math.round(leadPx * STACK_GAP_RATIO);
}

/**
 * Safe area as a fraction of each edge.
 *
 * Vertical reserves a large bottom margin because the platform owns it — the
 * caption, the handle, and the action rail all overlay the lowest fifth on Reels,
 * Shorts, and TikTok. Landscape reserves a uniform margin, since YouTube overlays
 * only a thin auto-hiding control bar.
 */
export const SAFE_AREA: Record<
  PersianFormat,
  { readonly top: number; readonly bottom: number; readonly side: number }
> = {
  vertical: { top: 0.08, bottom: 0.2, side: 0.08 },
  landscape: { top: 0.08, bottom: 0.08, side: 0.08 },
};

/**
 * Fraction of frame width text may occupy.
 *
 * Narrower than the safe area on purpose: text set to the full safe width reads
 * as filling the frame, and a measured margin beyond the technical limit is what
 * makes a composition look composed. The line budget derives from this, so the
 * measurement and the paint cannot disagree.
 */
export const TEXT_WIDTH_FRACTION = 0.84;

/**
 * Fraction of the budget reserved against per-span paint drift.
 *
 * The component paints each word as its own `inline-block` span, and Chromium
 * paints those spans ~2% wider than the canvas advance the fitter measured —
 * measured on real frames at +17px to +32px on lines that filled 99% of their
 * budget, which is the verify's `INK_OVERSHOOT` flag on lines the fitter had
 * every reason to believe fit. The drift does not scale away at other sizes or
 * formats, so it is charged as a fraction rather than a flat margin.
 *
 * `FIT_SAFETY_PX` remains as the flat part: antialiasing and rounding, which
 * do not scale with the frame.
 */
export const FIT_SPAN_DRIFT_FRACTION = 0.025;

/**
 * Paint charge for ZWNJ (U+200C) that the DOM path bills and canvas shaping does not.
 *
 * Each word is painted as an `inline-block` span with `unicodeBidi: "embed"`. In
 * that DOM path Chromium paints a ZWNJ as a `.notdef` advance; the canvas path
 * consumed by `measurePersian`/`measureWords` consumes it in shaping and charges
 * zero delta. The fitter therefore undercounts every ZWNJ-containing word and its
 * ink overshoots the text column. ZWNJ is not stripped — it correctly breaks
 * letter joins («شرکت‌کنندگان» ≠ «شرکتکنندگان») — so the fix is to charge for
 * it in measurement. Observed paint deltas are 0.30–0.53em across words/sizes;
 * charged at the observed maximum so the fitter never undercounts.
 */
export const ZWNJ_PAINT_CHARGE_EM = 0.53;

/** Safety margin subtracted from the measured line budget, px. */
export const FIT_SAFETY_PX = 4;

/**
 * Usable text width in px, derived rather than configured.
 *
 * Configuring it separately from the paint is the classic layout failure: text
 * measured against a width wider than the box it lands in overflows on exactly
 * the lines that are close to the limit, and only on those.
 */
export function computeLineBudgetPx(format: PersianFormat): number {
  const { width } = FORMAT_DIMENSIONS[format];
  const measured = width * TEXT_WIDTH_FRACTION;
  return (
    measured -
    FIT_SPAN_DRIFT_FRACTION * measured -
    FIT_SAFETY_PX
  );
}

/** Height of the frame a moment may use, in px — the safe area's inner box. */
export function computeUsableHeightPx(format: PersianFormat): number {
  const { height } = FORMAT_DIMENSIONS[format];
  const safe = SAFE_AREA[format];
  return height * (1 - safe.top - safe.bottom);
}

/** Height budget for one moment's whole stack, in px. */
export function computeMaxStackPx(format: PersianFormat): number {
  return computeUsableHeightPx(format) * TYPOGRAPHY[format].maxStackFraction;
}

/**
 * Optical centre of the moment zone, as a fraction of frame height.
 *
 * Derived from the safe area rather than set to 0.5, because the geometric centre
 * of the *frame* is not the centre of the *usable* frame. In vertical the bottom
 * fifth belongs to platform chrome, so text centred at 50% sits visually low; the
 * midpoint of the region actually available is 44%.
 *
 * Deriving it also means the value cannot drift out of agreement with
 * `SAFE_AREA`, which is how a hard-coded position ends up correct in the format
 * that was rendered and wrong in the other one.
 */
export function computeMomentCentreFraction(format: PersianFormat): number {
  const safe = SAFE_AREA[format];
  return (safe.top + (1 - safe.bottom)) / 2;
}

/** Height of the hairline rule above every moment, px. */
export const MOMENT_RULE_HEIGHT_PX = 3;

/**
 * Margin beyond the ink that the scrim plateau extends, px.
 *
 * Mirrors `SCRIM_PLATEAU_MARGIN_PX` in `PersianMomentBlock.tsx` and
 * `SCRIM_PLATEAU_MARGIN_PX` in `lib/persian_verify.py`. The plateau must cover
 * every row the moment's ink occupies plus this margin, because `peakAlpha` is
 * the only alpha the contrast floor was computed against.
 */
export const SCRIM_PLATEAU_MARGIN_PX = 28;

/**
 * Rows the scrim actually darkens at peak alpha for a given fitted stack.
 *
 * Derived from the fitted `stackHeightPx` and the optical centre — the same
 * derivation `PersianMomentBlock.tsx:scrimStops()` uses — plus the plateau
 * margin, so both sides stay in parity. The zone (`computeMomentZone`) is the
 * envelope of the tallest legal moment; the plateau is the per-moment darkened
 * band. Used by the verifier to scope ink measurement to rows the scrim
 * guarantees, and by the component to size the gradient.
 */
export function computeScrimPlateau(
  format: PersianFormat,
  stackHeightPx: number,
): { readonly topFraction: number; readonly bottomFraction: number } {
  const { height } = FORMAT_DIMENSIONS[format];
  const centre = computeMomentCentreFraction(format);
  const half = (stackHeightPx / 2 + SCRIM_PLATEAU_MARGIN_PX) / height;
  return { topFraction: centre - half, bottomFraction: centre + half };
}

/**
 * Height of the tallest moment a format permits, in px.
 *
 * This is now the height *budget* rather than a sum over a worst-case slot
 * arrangement, and they are the same number by construction: the fitter refuses
 * any stack taller than `computeMaxStackPx`, so the budget is exactly the
 * envelope the verifier should look inside. The predecessor computed a worst-case
 * sum over fixed slot sizes, which meant the zone and the fitter could disagree —
 * and did, whenever a size changed on one side only.
 */
export function computeTallestMomentPx(format: PersianFormat): number {
  return computeMaxStackPx(format) + MOMENT_RULE_HEIGHT_PX;
}

/**
 * Rows a moment's ink may occupy, as fractions of frame height.
 *
 * Derived from the height budget and the optical centre, so the verifier can
 * check that painted ink landed where the design says it should without either
 * side restating a literal. A moment outside this envelope means the layout
 * measured against something other than the vendored font.
 */
export function computeMomentZone(format: PersianFormat): {
  readonly topFraction: number;
  readonly bottomFraction: number;
} {
  const { height } = FORMAT_DIMENSIONS[format];
  const centre = computeMomentCentreFraction(format);
  const half = computeTallestMomentPx(format) / height / 2;
  return { topFraction: centre - half, bottomFraction: centre + half };
}

/**
 * Columns a moment's ink may occupy, in px.
 *
 * The right edge is the anchor every line shares; the left edge is the anchor
 * minus the line budget. Both derive from the same tokens the component positions
 * against, which is what lets a verifier assert the anchor without knowing the
 * text.
 *
 * This is the check that catches the specific regression the moment model exists
 * to prevent: text that drifted back to centre-aligned would land inside the
 * *width* budget but not against the *anchor*, and a width-only check would pass
 * it.
 */
export function computeMomentColumns(format: PersianFormat): {
  readonly leftPx: number;
  readonly rightPx: number;
} {
  const { width } = FORMAT_DIMENSIONS[format];
  const rightPx = width * (1 - SAFE_AREA[format].side);
  return { leftPx: rightPx - computeLineBudgetPx(format), rightPx };
}

/**
 * Where the watermark rests after migrating, as a percentage of frame height.
 *
 * Near the top in both formats, and above the moment zone in both — checked
 * rather than assumed by `computeWatermarkQuietTopPct` below.
 */
export const WATERMARK_RESTING_TOP_PCT: Record<PersianFormat, number> = {
  vertical: 11,
  landscape: 8,
};

/**
 * Gap between the quiet watermark and the top of the moment zone, as a
 * percentage of frame height. Enough that the mark's bloom cannot reach the text:
 * it grows about its own centre, so half the growth travels upward.
 */
export const WATERMARK_QUIET_CLEARANCE_PCT = 6;

/**
 * The watermark's quiet position, as a percentage of frame height.
 *
 * Derived, because a single hard-coded value cannot serve both formats. The
 * predecessor of this function was a flat 75%, which sat below the caption panel
 * in vertical and *inside* it in landscape, where the panel was 110px from the
 * bottom rather than 590px. The mark overlapped the first line of every landscape
 * subtitle and looked perfect in the format that had been rendered.
 *
 * The zone it clears is now the moment zone rather than a caption band, and the
 * zone grew when moments became phrases, so the derivation earns its keep a
 * second time: the mark moved up on its own.
 *
 * `Math.max`, not `min`. The quiet position is meant to be the *lower* of the two
 * — the mark announces itself near the middle of the frame, then migrates up to
 * the corner — so the derivation takes the largest top-percentage that still
 * clears the type, and the resting percentage is the floor beneath which it may
 * not rise. Swapping this to `min` collapses quiet onto resting, which type-checks,
 * renders, and silently deletes the migration phase: the mark simply sits in the
 * corner for the whole video and nothing looks broken enough to notice.
 */
export function computeWatermarkQuietTopPct(format: PersianFormat): number {
  const zone = computeMomentZone(format);
  return Math.max(
    WATERMARK_RESTING_TOP_PCT[format],
    zone.topFraction * 100 - WATERMARK_QUIET_CLEARANCE_PCT,
  );
}

// ---------------------------------------------------------------------------
// Reading time
// ---------------------------------------------------------------------------

/**
 * Reading rate, visible characters per second.
 *
 * Deliberately far below a subtitle's 21: a caption is read while listening, but
 * a moment is *looked at*, and the eye needs time to take in the composition
 * before it starts reading. Measured with `visibleLength`, so ZWNJ and combining
 * marks are not charged.
 */
export const MOMENT_READ_CPS = 11;

/**
 * Dead time at the start of a moment — and of every later build step — before
 * any reading happens, in seconds.
 *
 * The entrance itself takes `ENTER_FRAMES` (13 frames ≈ 0.43s at 30fps) during
 * which the type is translating and blurred, and the eye then needs a beat to
 * land on it. Charging only characters, as the predecessor did, is what let a
 * 2.03s moment be declared adequate for 22 characters: arithmetically 2.0s of
 * reading, in practice about 1.5s once the entrance is subtracted, which is the
 * "متن‌ها گاهی بیش از حد سریع رد میشن" complaint measured.
 */
export const MOMENT_FIXATION_SECONDS = 0.45;

/**
 * Cost of each additional block in the same reveal step, in seconds.
 *
 * A moment's phrase is set as two or three separate blocks — lead, hero, tail —
 * and the eye must land on each one: a saccade plus a refixation that the
 * character count does not see. Charged per block rather than per rendered *line*
 * because the line count is only known after the ladder search runs on canvas, and
 * the pacing gate has to hold in the pipeline, before any browser is involved.
 *
 * A block that wraps to two lines therefore costs the same as a one-line block,
 * which under-charges it. That is the honest limitation of gating pacing without
 * the font; the per-block figure is set generously to absorb it, and the width
 * ceilings on each role keep any single block from wrapping far.
 */
export const MOMENT_BLOCK_SECONDS = 0.3;

/**
 * Weight applied to a `source` segment's characters in the reading model.
 *
 * Less than one, because a citation set in the smallest type is not read the way
 * the phrase above it is read — a viewer who does not care about the provenance
 * skips it, and one who does will pause. Not zero, because it is still ink on the
 * screen competing for the same few seconds.
 */
export const MOMENT_SOURCE_READ_WEIGHT = 0.5;

/**
 * Floor on a moment's screen time.
 *
 * Raised from 1.8s: with fixation charged separately, 1.8s of total screen time
 * leaves under 1.4s of reading, which is not enough for any phrase worth setting
 * in type. A moment shorter than this should be cut rather than shortened.
 */
export const MOMENT_MIN_SECONDS = 2.4;

/**
 * Ceiling on a moment's screen time.
 *
 * Not a readability limit — a long moment is perfectly readable. It is a pacing
 * limit: past this a static frame of text stops feeling composed and starts
 * feeling stalled, and the footage behind it is doing nothing.
 *
 * Raised from 6s alongside the reading model, because a built moment legitimately
 * holds longer: it is two or three reads, not one.
 */
export const MOMENT_MAX_SECONDS = 9;

/**
 * Minimum gap of empty frame between consecutive moments.
 *
 * This is the token that makes the pipeline's output structurally different from
 * a caption track, so it is stated as a hard number rather than left to taste.
 * Without a floor here an agent fills every pause and the result is a subtitle
 * track with fancier type — which is exactly what happened before the moment
 * model existed. 0.9s is long enough to register as deliberate silence rather
 * than as a gap between cues.
 *
 * A *build step inside* one moment is not a new moment and is not subject to it:
 * that is the whole point of building, and it is why the additive case is a
 * segment reveal rather than a second moment with a relaxed gap.
 */
export const MOMENT_MIN_GAP_SECONDS = 0.9;

/**
 * Latest the first moment may appear, in seconds.
 *
 * ## Why an opening moment is required, when the opening *hook layer* was deleted
 *
 * These are not the same thing, and the distinction is the whole reason this is a
 * timing rule rather than a new component. The deleted `hookText` was a *second
 * text layer* with its own position and its own timing, independent of the
 * caption layer, and nothing suppressed either while the other was up: the
 * opening seconds painted a red hook at 18% of frame height and the identical
 * sentence as a caption at 61%, simultaneously. What was wrong with it was the
 * extra layer, not the idea of opening with type.
 *
 * Meanwhile a video that opens on silent footage is a video most viewers never
 * hear: short-form feeds autoplay muted, so for the first second or two the
 * narration — which carries every sentence in this design — does not exist. An
 * empty opening frame is therefore not restraint, it is a blank first impression,
 * and it is the one place where "the voice will explain" is false by construction.
 *
 * So the first moment must be on screen essentially from the start. It is an
 * ordinary moment in the ordinary moments layer, subject to the same gap floor,
 * the same reading model, and the same coverage ceiling — there is still exactly
 * one text layer in this composition (the deleted `hookText` second layer is
 * what went), which is what makes the overlap that killed the hook layer
 * unrepresentable. Four moment *kinds* remain — figure, term, statement, hook —
 * but kinds are editorial classification, not layers.
 *
 * 0.6s rather than 0.0s because a moment that is already fully arrived on frame 0
 * has no entrance, and a hard-cut appearance on the first frame reads as a still
 * image rather than as an opening. 0.6s covers the entrance and lands the type
 * before a thumb decides.
 *
 * ## Why this does not conflict with narration anchoring
 *
 * Every other moment is anchored to the words it belongs to. The opening moment is
 * anchored too — to the first phrase of the narration — and the constraint is that
 * the *script* must open on something worth setting in type. When it does not, the
 * remedy is the script, not a moment floated free of the voice: a first frame that
 * says something the narration is not saying is the "حس سینک بودن" failure at the
 * worst possible moment.
 */
export const OPENING_MOMENT_MAX_START_SECONDS = 0.6;
