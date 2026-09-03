/**
 * One typographic moment.
 *
 * A moment is **one Persian phrase, set in the order the language needs it, with
 * one emphasised span inside it**. The segment array is the paint order, top to
 * bottom, and this component adds no reordering of its own: what the author wrote
 * first appears first. That is load-bearing rather than incidental — Persian
 * states the frame before the fact («مطالعهٔ دانشگاه اولوی فنلاند روی» *then*
 * «۲۲۶۴ نفر»), and a component that sorted by role, or that always put supporting
 * text below the hero, would break the sentence in exactly the cases where the
 * grammar matters most.
 *
 * ## What this replaced
 *
 * The predecessor arranged four slots by `kind`: `kicker` above, hero in the
 * middle, `unit` in a baseline-aligned row beside the hero, `label` below. For a
 * study of 2264 people that produced a 260px accent numeral, «نفر» floating at the
 * numeral's baseline 550px to its left, and «دانشگاه اولو، فنلاند» on a third
 * line — three sizes, three left edges, and nothing on screen saying a study was
 * being described. The information was all present; the sentence was missing.
 *
 * Three things changed, and each answers a specific defect:
 *
 * 1. **Segments, not slots.** The unit is inside the hero text («۲۲۶۴ نفر»)
 *    because that is how the quantity is spoken, so there is nothing to float.
 * 2. **One size per moment.** `fitMoment` picks the hero rung; everything else is
 *    a fixed proportion of it. A 5.9:1 size ratio between a numeral and its label,
 *    and a 2.1:1 ratio between a scoping line and its claim, were both symptoms of
 *    sizes chosen per slot rather than per phrase.
 * 3. **Ink-trimmed rows.** Gaps are measured between real ink boxes, so a declared
 *    34px gap is 34px on screen. The shipped render's 133px hole between a numeral
 *    and its label was half-leading — a property of Estedad's line box, not of any
 *    gap token, and therefore invisible to anyone reading the gap tokens.
 *
 * ## Right-anchored, not centred
 *
 * Centred text over footage is the single strongest visual signature of automatic
 * captioning: every line finds its own centre, so consecutive lines shift left
 * and right against each other and nothing in the frame holds still. Editorial
 * Persian typesetting anchors to a margin instead. Here every line of every
 * moment shares one right edge at the safe-area margin, so the type has a spine.
 * The ragged edge lands on the left, which under RTL is the trailing edge — the
 * same place a well-set Latin page puts its rag.
 *
 * ## A gradient wash, not a panel
 *
 * A rounded rectangle behind text reads as an interface element. It was the right
 * answer for captions, where a bounded box guarantees local contrast for a line
 * that is always on screen, and it is the wrong answer here: a moment is a
 * composition on the frame, not a widget over it. The wash peaks behind the ink,
 * reaches zero before the frame edges, and leaves the corners of every shot at
 * full exposure.
 *
 * ## The motion rule this file must not break
 *
 * Settled text is never transformed. Once a line has arrived it may change only
 * in glow alpha and brightness (`holdLife`), because a sub-pixel transform forces
 * the rasterizer to re-snap glyph outlines every frame and the result is a visible
 * shimmer along the letters — worst on Persian, whose joining strokes are thin,
 * horizontal, and run the full width of a word. The rule is why the hairline rule
 * animates `scaleX` (a solid rectangle has no outlines to re-snap) while the type
 * animates only during its entrance.
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import { ESTEDAD_FAMILY } from "../fonts";
import { compareKey } from "../text";
import {
  fitMoment,
  inkTrimMargins,
  isClaimQualifierHook,
  isFlatDisplayBlock,
  type FittedMoment,
  type FittedSegment,
} from "../layout";
import { glow, holdLife, materialEnter, materialExit, staggerDelay } from "../motion";
import {
  computeScrimPlateau,
  FONT_ASCENT_EM,
  FONT_DESCENT_EM,
  FORMAT_DIMENSIONS,
  HOOK_SEGMENT_STAGGER_FRAMES,
  MOMENT_RULE_HEIGHT_PX,
  PERSIAN_PALETTE,
  ROW_LINE_HEIGHT,
  SCRIM,
  SCRIM_PLATEAU_MARGIN_PX,
  TYPOGRAPHY,
  computeMomentCentreFraction,
  computeMomentColumns,
  type PersianFormat,
} from "../tokens";
import {
  assertMomentIsWellFormed,
  type PersianMoment,
  type PersianSegmentRole,
} from "../types";

export interface PersianMomentBlockProps {
  readonly moment: PersianMoment;
  readonly format: PersianFormat;
  /** Frames this moment occupies, for its exit timing. */
  readonly durationFrames: number;
}

/**
 * Vertical falloff stops for the scrim, in percent of frame height.
 *
 * The wash is a vertical band rather than a radial blob so that the contrast
 * arithmetic in `SCRIM` holds exactly at every row the ink can occupy: a radial
 * gradient's alpha depends on horizontal distance too, so a long line's outer
 * words would sit at a lower alpha than the value the contrast floor was computed
 * against. A band has one alpha per row, which is the assumption the floor makes.
 *
 * The plateau margin and the derived plateau rows live in `tokens.ts`
 * (`SCRIM_PLATEAU_MARGIN_PX`, `computeScrimPlateau`) so the verifier can mirror
 * them. This file imports that single source rather than restating the constant.
 */

function scrimStops(
  format: PersianFormat,
  stackHeightPx: number,
): {
  fadeInStart: number;
  plateauStart: number;
  plateauEnd: number;
  fadeOutEnd: number;
} {
  const { width, height } = FORMAT_DIMENSIONS[format];
  const shorterAxis = Math.min(width, height);
  const falloffPct = ((SCRIM.falloffFraction * shorterAxis) / height) * 100;
  const centre = computeMomentCentreFraction(format) * 100;

  // The plateau must cover every row *this moment's* type occupies, because
  // `peakAlpha` is the only alpha the contrast floor was computed against: ink
  // sitting on the falloff instead of the plateau is on a lighter background than
  // the guarantee assumes. Sized from the fitted stack rather than the zone
  // (see `computeScrimPlateau`).
  const plateau = computeScrimPlateau(format, stackHeightPx);
  const halfPct = ((plateau.bottomFraction - plateau.topFraction) / 2) * 100;
  return {
    fadeInStart: centre - halfPct - falloffPct,
    plateauStart: centre - halfPct,
    plateauEnd: centre + halfPct,
    fadeOutEnd: centre + halfPct + falloffPct,
  };
}

/**
 * The wash behind a moment.
 *
 * Two stacked gradients. The vertical band carries the contrast guarantee; the
 * horizontal one is pure art direction — it deepens toward the right margin where
 * the type is anchored, so the darkening reads as light falling across the frame
 * rather than as a bar laid over it. The horizontal layer only ever *adds*
 * darkness, so it cannot undercut the floor the vertical layer establishes.
 */
const MomentScrim: React.FC<{
  readonly format: PersianFormat;
  readonly opacity: number;
  readonly stackHeightPx: number;
}> = ({ format, opacity, stackHeightPx }) => {
  const stops = scrimStops(format, stackHeightPx);
  const peak = SCRIM.peakAlpha;

  const vertical =
    `linear-gradient(to bottom,` +
    ` rgba(0,0,0,0) ${stops.fadeInStart.toFixed(2)}%,` +
    ` rgba(0,0,0,${peak}) ${stops.plateauStart.toFixed(2)}%,` +
    ` rgba(0,0,0,${peak}) ${stops.plateauEnd.toFixed(2)}%,` +
    ` rgba(0,0,0,0) ${stops.fadeOutEnd.toFixed(2)}%)`;

  const horizontal =
    `linear-gradient(to left,` +
    ` rgba(0,0,0,0.22) 0%,` +
    ` rgba(0,0,0,0.10) 45%,` +
    ` rgba(0,0,0,0) 78%)`;

  return (
    <AbsoluteFill
      style={{
        backgroundImage: `${vertical}, ${horizontal}`,
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

/** Ink colour per role. Only the hero is accented — see `PERSIAN_PALETTE`. */
const ROLE_COLOR: Record<PersianSegmentRole, string> = {
  lead: PERSIAN_PALETTE.ink,
  hero: PERSIAN_PALETTE.accent,
  tail: PERSIAN_PALETTE.ink,
  source: PERSIAN_PALETTE.inkSecondary,
};

/** Glow radius per role, px. Only display-size accent type needs one. */
const ROLE_GLOW_PX: Record<PersianSegmentRole, number> = {
  lead: 0,
  hero: 22,
  tail: 0,
  source: 0,
};

/**
 * One already-fitted segment, painted.
 *
 * Takes a `FittedSegment` rather than raw text because the size decision belongs
 * to the moment, not to the segment: fitting here would reintroduce the per-slot
 * sizing this design exists to remove.
 *
 * Each row is trimmed to its measured ink, so the flex `gap` between rows and the
 * `gap` between segments both describe visible space.
 */
const SegmentLines: React.FC<{
  readonly segment: FittedSegment;
  readonly startFrame: number;
  readonly endFrame: number;
  readonly stagger: boolean;
  readonly wordGapPx: number;
  /** Extra opacity multiplier — below 1 once a later build step has arrived. */
  readonly dim: number;
}> = ({ segment, startFrame, endFrame, stagger, wordGapPx, dim }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Flat-hook treatment: when the segment names accent words, the whole block
  // paints at its one fitted size and only those words carry the accent — the
  // emphasis expressed in colour rather than size. Every other segment keeps
  // the role colour for every word, exactly as before.
  const accentSet = React.useMemo(
    () => new Set((segment.accentWords ?? []).map(compareKey)),
    [segment.accentWords],
  );
  const flat = accentSet.size > 0;
  const baseColor = ROLE_COLOR[segment.role];
  const baseGlowPx = ROLE_GLOW_PX[segment.role];
  const springWeight = segment.role === "hero" ? "hero" : "standard";
  let wordCursor = 0;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: segment.lineGapPx,
        direction: "rtl",
      }}
    >
      {segment.lines.map((line, lineIndex) => {
        const ink = segment.inkPerLine[lineIndex];
        const trim = inkTrimMargins(
          ink,
          segment.fontSizePx,
          FONT_ASCENT_EM,
          FONT_DESCENT_EM,
        );

        return (
          <div
            key={lineIndex}
            style={{
              display: "flex",
              flexDirection: "row",
              // RTL on the row, so source order is reading order and the first word
              // sits at the right edge. Reversing the array instead would break the
              // bidi algorithm for any embedded Latin token or numeral.
              direction: "rtl",
              // Anchored right, never centred — this is the spine.
              //
              // `flex-start`, not `flex-end`: flex alignment is logical, and under
              // `direction: rtl` the main axis runs right-to-left, so main-start *is*
              // the right edge. Writing `flex-end` here is the natural mistake and it
              // silently anchors the whole video to the left margin instead. Do not
              // "fix" this to `flex-end`.
              justifyContent: "flex-start",
              alignItems: "baseline",
              gap: wordGapPx,
              // The row box is exactly the font's line box tall, which puts the
              // baseline at a known offset; the margins then collapse the box onto
              // the glyphs. See `inkTrimMargins`.
              lineHeight: ROW_LINE_HEIGHT,
              marginTop: trim.marginTopPx,
              marginBottom: trim.marginBottomPx,
              flexWrap: "nowrap",
              whiteSpace: "nowrap",
            }}
          >
            {line.map((word) => {
              const index = wordCursor;
              wordCursor += 1;

              const wordStart = stagger ? startFrame + staggerDelay(index) : startFrame;
              const enter = materialEnter(frame, wordStart, fps, springWeight);
              const exit = materialExit(frame, endFrame, fps, "standard");
              const opacity = Math.min(enter.opacity, exit.opacity) * dim;
              const life = holdLife(frame, index * 7);

              const isAccent = flat && accentSet.has(compareKey(word));
              const color = flat
                ? isAccent
                  ? PERSIAN_PALETTE.accent
                  : PERSIAN_PALETTE.ink
                : baseColor;
              const glowRadiusPx = flat
                ? isAccent
                  ? baseGlowPx
                  : 0
                : baseGlowPx;

              const settled = enter.transform === "none" && exit.transform === "none";
              const shadows: string[] = [];
              if (glowRadiusPx > 0) {
                shadows.push(glow(color, glowRadiusPx, 0.5 * life.glowAlpha));
              }
              // A soft drop under every glyph, so the type survives the moment the
              // scrim is still fading in and has not reached its plateau alpha.
              shadows.push("0px 2px 6px rgba(0,0,0,0.55)");

              return (
                <span
                  key={`${index}-${word}`}
                  style={{
                    fontFamily: ESTEDAD_FAMILY,
                    fontWeight: segment.weight,
                    fontSize: segment.fontSizePx,
                    color,
                    opacity,
                    textShadow: shadows.join(", "),
                    // Settled type carries no transform at all — see the module note.
                    transform: settled
                      ? "none"
                      : `${enter.transform === "none" ? exit.transform : enter.transform}`,
                    filter: enter.filter,
                    // `embed` isolates each word's bidi run, so a Latin token or a
                    // numeral inside a Persian line does not reorder its neighbours.
                    unicodeBidi: "embed",
                    direction: "rtl",
                    display: "inline-block",
                  }}
                >
                  {word}
                </span>
              );
            })}
          </div>
        );
      })}
    </div>
  );
};

/**
 * The hairline rule above a moment.
 *
 * A compositional device rather than decoration: it establishes the right margin
 * before any type arrives, so the moment reads as placed on a grid instead of
 * floating. It animates `scaleX` from the right edge — legal on a solid
 * rectangle, which has no glyph outlines to re-snap against the pixel grid.
 */
const MomentRule: React.FC<{
  readonly widthPx: number;
  readonly startFrame: number;
  readonly endFrame: number;
  readonly color: string;
}> = ({ widthPx, startFrame, endFrame, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = materialEnter(frame, startFrame, fps, "light");
  const exit = materialExit(frame, endFrame, fps, "light");
  const progress = Math.min(enter.opacity, exit.opacity);

  return (
    <div
      style={{
        width: widthPx,
        height: MOMENT_RULE_HEIGHT_PX,
        backgroundColor: color,
        transform: `scaleX(${progress.toFixed(4)})`,
        // Grows from the right, so it draws outward from the same spine the type
        // is anchored to. A physical edge, not a logical one, because a transform
        // origin is unaffected by `direction`.
        transformOrigin: "right center",
        opacity: progress,
      }}
    />
  );
};

/**
 * Frames after the block's own start at which the last word of a flat display
 * hook may still arrive. A flat hook is a *sentence*, and staggering it word by
 * word is what makes the phrase feel written rather than pasted — but a hook
 * whose last word lands late eats the reading window. (Measured example, one
 * project: the shipped flat hook sat only 0.19s clear of the pacing gate, which
 * is why the bound bites there.) Past this bound the hero keeps arriving
 * as one mass instead.
 */
const FLAT_HOOK_STAGGER_ARRIVAL_SECONDS = 0.35;

/**
 * Whether a fitted segment is a flat display hook whose words may stagger.
 *
 * A flat display hero is a sentence rather than a numeral, so the "a display
 * numeral staggered word by word reads as a counter" reason the hero arrives
 * as one mass does not apply to it. Gated mechanically rather than by taste:
 * the last of the hook's words must arrive within
 * `FLAT_HOOK_STAGGER_ARRIVAL_SECONDS` of the block's start at 30fps, decided
 * from `staggerDelay` (which clamps at `MAX_STAGGER_FRAMES`) and the fitted
 * word count. `fps` is fixed at 30 — the composition's own `PERSIAN_FPS` —
 * because this is an arrival budget in seconds, not a frame count.
 */
export function flatHookStaggers(fitted: FittedSegment): boolean {
  if (fitted.accentWords.length === 0) return false;
  const wordCount = fitted.lines.reduce((total, line) => total + line.length, 0);
  if (wordCount === 0) return false;
  return staggerDelay(wordCount - 1) / 30 <= FLAT_HOOK_STAGGER_ARRIVAL_SECONDS;
}

/**
 * Frames after a segment's own arrival at which the *next* segment arrives, when
 * the author did not ask for a build.
 *
 * Small and cumulative: the eye reads down the phrase, so the lines arriving in
 * reading order at a few frames apart feels like the sentence being spoken rather
 * than like a slide appearing. This is a *stagger*, not a build — every segment is
 * on screen within a third of a second and the reading model charges the moment as
 * one read.
 *
 * A build is the other thing, and it is authored: a segment with
 * `revealAfterSeconds` set joins the phrase seconds later, previous segments
 * staying put, and `lib/persian_moments.py` charges each step its own reading time.
 *
 * A claim+qualifier hook staggers longer (`HOOK_SEGMENT_STAGGER_FRAMES`, 9
 * frames ≈ 0.3s) than this ordinary 5-frame beat: the claim lands, then the
 * qualifier completes it — two beats of one sentence. Both lines arrive as one
 * mass each; `stagger` below is false for both, because a claim arriving word
 * by word stops reading as a claim. (Measured example, one project: with the
 * 13-frame entrance the qualifier settled at frame 22 of a 4.2s opening moment,
 * well inside its window — the 4.2s was that project's moment length, not a
 * hook-window token.)
 */
const SEGMENT_STAGGER_FRAMES = 5;

/**
 * Opacity of a step that an authored build has superseded.
 *
 * The point of a build is that the earlier line is still *there* — the reader who
 * needed longer on it has it, and the new line lands as an addition to a phrase
 * rather than as a replacement for one. Dimming rather than removing is what makes
 * that legible: at full strength two steps compete for the eye, and at zero the
 * build is just a cut. 0.55 is far enough down to hand the emphasis to the new
 * step while leaving the old one readable — it is still primary ink over the
 * scrim, so it clears the contrast floor with room to spare.
 */
const SUPERSEDED_OPACITY = 0.55;

export const PersianMomentBlock: React.FC<PersianMomentBlockProps> = ({
  moment,
  format,
  durationFrames,
}) => {
  assertMomentIsWellFormed(moment);

  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const typography = TYPOGRAPHY[format];
  const { width, height } = FORMAT_DIMENSIONS[format];
  const columns = computeMomentColumns(format);

  // Fitting is a pure function of (segments, format, kind), so it memoizes on
  // exactly those. Re-measuring on canvas 30 times a second for a result that
  // cannot change is the easiest performance mistake to make here. The kind is
  // declared on the moment — never inferred — so a claim+qualifier hook keeps
  // its hook-scoped tokens rather than silently rendering as an ordinary moment.
  const fitted: FittedMoment = React.useMemo(
    () => fitMoment(moment.segments, format, moment.kind),
    [moment.segments, moment.kind, format],
  );
  // The scrim leads the type in and trails it out, so the wash is never a hard
  // edge appearing with the words. Its own fade is independent of the spring the
  // type uses, because a spring on a full-frame gradient reads as a flicker.
  const scrimOpacity = React.useMemo(() => {
    const inProgress = Math.min(1, Math.max(0, frame / SCRIM.fadeFrames));
    const outProgress = Math.min(
      1,
      Math.max(0, (durationFrames - frame) / SCRIM.fadeFrames),
    );
    return Math.min(inProgress, outProgress);
  }, [frame, durationFrames]);

  const endFrame = durationFrames;
  const heroIndex = fitted.segments.findIndex((segment) => segment.role === "hero");

  /**
   * The most recent build step to have arrived, as a frame offset within the
   * moment. 0 while the moment is on its first step.
   *
   * Every segment authored *before* this step dims — computed from the current
   * frame rather than tracked as state, because a Remotion component may be
   * rendered at any frame in any order and state that assumes forward playback
   * produces different output for a still than for the video.
   */
  const activeRevealFrame = React.useMemo(() => {
    let active = 0;
    for (const segment of fitted.segments) {
      if (segment.role === "source") continue;
      const reveal = Math.round(segment.revealAfterSeconds * fps);
      if (reveal <= frame && reveal > active) active = reveal;
    }
    return active;
  }, [fitted.segments, fps, frame]);

  // The rule spans the hero's own width rather than a fixed fraction of the frame,
  // so it reads as belonging to this phrase. Floored so a two-character hero still
  // gets a visible mark, and capped at the text column so it never overhangs.
  const ruleWidth = Math.round(
    Math.min(
      columns.rightPx - columns.leftPx,
      Math.max(width * 0.12, fitted.segments[Math.max(0, heroIndex)].widthPx * 0.5),
    ),
  );

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <MomentScrim
        format={format}
        opacity={scrimOpacity}
        stackHeightPx={fitted.heightPx}
      />

      <div
        style={{
          position: "absolute",
          // Optically centred on the usable frame rather than the whole frame:
          // in vertical the bottom fifth belongs to platform chrome, so text
          // centred at 50% sits visually low.
          top: computeMomentCentreFraction(format) * height,
          transform: "translateY(-50%)",
          // Anchored right and sized to the text column, so every line of every
          // moment in the video shares one right edge. Both numbers come from
          // `computeMomentColumns`, which is also what the frame verifier checks
          // the painted ink against — one source, so a drift back to centred text
          // fails rather than silently passing a width-only test.
          right: width - columns.rightPx,
          width: columns.rightPx - columns.leftPx,
          display: "flex",
          flexDirection: "column",
          // Cross-axis alignment on a column is the inline axis, which under
          // `direction: rtl` starts at the right — so `flex-start` is the right
          // edge here too, for the same reason as the rows above.
          alignItems: "flex-start",
          gap: fitted.stackGapPx,
          direction: "rtl",
        }}
      >
        <MomentRule
          widthPx={ruleWidth}
          startFrame={0}
          endFrame={endFrame}
          color={PERSIAN_PALETTE.accent}
        />

        {/* Segments in authored order. No sorting, no role-priority: the array
            order is the reading order of one Persian phrase, and the author chose
            it because the grammar requires it. */}
        {fitted.segments.map((segment, index) => {
          const authoredReveal = Math.round(segment.revealAfterSeconds * fps);
          // A claim+qualifier hook arrives in two beats — the claim, then the
          // qualifier 9 frames later — rather than on the ordinary 5-frame
          // stagger. Both beats arrive as one mass (see `stagger` below): the
          // two-beat rhythm is between the lines, never inside them.
          const hookBeat =
            moment.kind === "hook" &&
            isClaimQualifierHook(moment.segments) &&
            authoredReveal === 0;
          const startFrame = authoredReveal > 0
            ? authoredReveal
            : hookBeat
              ? index * HOOK_SEGMENT_STAGGER_FRAMES
              : index * SEGMENT_STAGGER_FRAMES;

          // A build step dims once a later step arrives, so the newest line owns the
          // emphasis while everything before it stays readable. `source` never dims:
          // it is a citation on the whole moment, not part of any step.
          const dim =
            segment.role !== "source" && authoredReveal < activeRevealFrame
              ? SUPERSEDED_OPACITY
              : 1;

          return (
            <SegmentLines
              key={`${segment.role}-${index}`}
              segment={segment}
              startFrame={startFrame}
              endFrame={endFrame}
              // A flat display hook is a *sentence*, not a numeral: its words
              // stagger in reading order, which is what makes the phrase feel
              // written rather than pasted. Every other hero still arrives as one
              // mass — a display numeral staggered word by word reads as a
              // counter — and both lines of a claim+qualifier hook arrive as one
              // mass each: a claim arriving word by word stops reading as a
              // claim, and the two-beat rhythm lives in the 9-frame stagger
              // between the lines, never inside them. The flat-hook branch
              // is arrival-gated inside `flatHookStaggers` (0.35s): a hook whose
              // last word would land late keeps arriving as one mass so it does
              // not eat its own reading window.
              stagger={
                segment.role !== "hero" ||
                (flatHookStaggers(segment) &&
                  isFlatDisplayBlock(moment.segments))
              }
              wordGapPx={Math.round(segment.fontSizePx * typography.wordGapRatio)}
              dim={dim}
            />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** Exported for tests: the fps-independent frame at which a hero begins arriving. */
export const MOMENT_HERO_START_FRAME = 0;
