/**
 * Four-phase animated watermark.
 *
 * The lockup is «طریقت تسلیم | @Pathway_of_Surrender». It announces itself once,
 * near the centre, then migrates to a corner and stays out of the way — so a
 * viewer who watches the whole piece sees the brand clearly without it competing
 * with the subtitles for the rest of the runtime.
 *
 * ## The four phases
 *
 * All phase boundaries derive from `durationInFrames`, so the same component
 * behaves correctly on a 20-second clip and a 10-minute one without tuning.
 *
 *   1. **Quiet** (0 → 20% of duration): low opacity, centred horizontally and resting
 *      just above the subtitle band. Present but not asserting.
 *   2. **Bloom** (60 frames): opacity to full, a slight scale up, and a golden
 *      glow ramps in. This is the beat that registers the brand.
 *   3. **Decay** (60 frames): everything returns to the quiet level.
 *   4. **Migration** (remainder): travels to the corner and holds there.
 *
 * ## The two details that are easy to get wrong
 *
 * **The corner anchor.** While centred, the element is positioned at `left: 50%`
 * with `translateX(-50%)` so its own centre lands on the frame centre. At the
 * corner, `left: 10%` should mean the element's *left edge* at 10%, which requires
 * `translateX(0%)`. So the translate must animate from -50% to 0% alongside the
 * position — animating position alone leaves the element offset by half its own
 * width, a bug that only shows on long text.
 *
 * **Bidi in the lockup.** Persian and Latin are separate `<span>`s with explicit
 * `dir` attributes inside an RTL flex row, rather than one mixed text node. In a
 * single node the Unicode bidi algorithm places the neutral `|` and the leading
 * `@` by surrounding context, which puts the separator on the wrong side of the
 * Latin handle. Explicit spans remove the ambiguity.
 *
 * **The quiet position is derived, not chosen.** It must clear the subtitle band, and
 * that band is in a different place in each format — 52% of the height in vertical,
 * 68% in landscape. A single hard-coded percentage put the mark on top of every
 * landscape subtitle's first line while looking correct in vertical.
 */

import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

import { ESTEDAD_FAMILY } from "../fonts";
import {
  PERSIAN_PALETTE,
  TYPOGRAPHY,
  WATERMARK_RESTING_TOP_PCT,
  computeWatermarkQuietTopPct,
  type PersianFormat,
} from "../tokens";
import { DEFAULT_WATERMARK, type PersianWatermark } from "../types";

export interface PersianWatermarkProps {
  readonly format: PersianFormat;
  readonly watermark?: PersianWatermark;
}

/** Base shadow, always present so the mark is legible over bright footage. */
const BASE_TEXT_SHADOW = "0px 2px 6px rgba(0,0,0,0.85)";

const BLOOM_FRAMES = 60;
const DECAY_FRAMES = 60;
const QUIET_OPACITY = 0.6;
const BLOOM_SCALE = 1.15;

export const PersianWatermarkMark: React.FC<PersianWatermarkProps> = ({
  format,
  watermark = DEFAULT_WATERMARK,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const typography = TYPOGRAPHY[format];

  const quietEnd = Math.floor(durationInFrames * 0.2);
  const bloomEnd = quietEnd + BLOOM_FRAMES;
  const decayEnd = bloomEnd + DECAY_FRAMES;

  // On a clip too short to contain all four phases, the ranges below would not
  // be strictly increasing and `interpolate` throws. Collapsing to the quiet
  // state is the honest fallback: there is no room for a bloom.
  const hasRoomForPhases = durationInFrames > decayEnd + 30;

  const opacity = hasRoomForPhases
    ? interpolate(
        frame,
        [0, quietEnd, bloomEnd, decayEnd],
        [QUIET_OPACITY, QUIET_OPACITY, 1, QUIET_OPACITY],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      )
    : QUIET_OPACITY;

  const scale = hasRoomForPhases
    ? interpolate(
        frame,
        [0, quietEnd, bloomEnd, decayEnd],
        [1, 1, BLOOM_SCALE, 1],
        {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
          easing: Easing.inOut(Easing.ease),
        },
      )
    : 1;

  const glowStrength = hasRoomForPhases
    ? interpolate(frame, [quietEnd, bloomEnd, decayEnd], [0, 1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 0;

  // Migration runs from the end of the decay to shortly after, then holds.
  const migrationEnd = decayEnd + 45;
  const migration = hasRoomForPhases
    ? interpolate(frame, [decayEnd, migrationEnd], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
        easing: Easing.inOut(Easing.ease),
      })
    : 1;

  // Both positions come from the tokens, which derive the quiet one from the subtitle
  // band. See `computeWatermarkQuietTopPct` for why it cannot be a constant.
  const restingTopPct = WATERMARK_RESTING_TOP_PCT[format];
  const quietTopPct = computeWatermarkQuietTopPct(format);

  const topPct = interpolate(migration, [0, 1], [quietTopPct, restingTopPct]);
  const leftPct = interpolate(migration, [0, 1], [50, 10]);
  const translateXPct = interpolate(migration, [0, 1], [-50, 0]);

  const shadows = [BASE_TEXT_SHADOW];
  if (glowStrength > 0.01) {
    shadows.push(
      `0 0 12px rgba(${PERSIAN_PALETTE.watermarkGlowRgb}, ${(glowStrength * 0.9).toFixed(3)})`,
      `0 0 28px rgba(${PERSIAN_PALETTE.watermarkGlowRgb}, ${(glowStrength * 0.5).toFixed(3)})`,
    );
  }

  return (
    <div
      style={{
        position: "absolute",
        top: `${topPct}%`,
        left: `${leftPct}%`,
        transform: `translateX(${translateXPct}%) scale(${scale.toFixed(4)})`,
        opacity,
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        // RTL row so the Persian name leads, matching how the brand is read.
        direction: "rtl",
        fontFamily: ESTEDAD_FAMILY,
        fontWeight: 500,
        fontSize: typography.watermarkFontSizePx,
        color: PERSIAN_PALETTE.text,
        textShadow: shadows.join(", "),
        whiteSpace: "nowrap",
        pointerEvents: "none",
        // Above footage and subtitles, below nothing — the mark is never covered.
        zIndex: 5,
      }}
    >
      <span dir="rtl">{watermark.persianText}</span>
      <span aria-hidden="true" style={{ opacity: 0.6 }}>
        |
      </span>
      <span dir="ltr">{watermark.latinText}</span>
    </div>
  );
};
