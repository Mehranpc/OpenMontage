/**
 * Five-phase animated watermark.
 *
 * The lockup is «طریقت تسلیم | @Pathway_of_Surrender». It stays hidden for the
 * opening, then announces itself once near the centre, migrates to a corner and
 * stays out of the way — so a viewer who watches the whole piece sees the brand
 * clearly without it competing with the opening typography.
 *
 * ## The five phases
 *
 * All phase boundaries derive from `durationInFrames`, so the same component
 * behaves correctly on a 20-second clip and a 10-minute one without tuning.
 *
 *   0. **Hidden** (0 → `INTRO_HIDDEN_FRAMES`): nothing paints. The opening
 *      moment is the hook and owns the first impression alone.
 *   1. **Quiet** (fade-in → 20% of duration): low opacity, centred horizontally
 *      and resting just above the moment zone. Present but not asserting.
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
 * **The quiet position is derived, not chosen.** It must clear the rows the
 * typographic layer can occupy, and those rows sit in a different place in each
 * format. When this was one hard-coded percentage it put the mark on top of every
 * landscape line while looking correct in vertical — the format that had been
 * rendered. See `computeMomentZone` for the current derivation.
 */

import React from "react";
import { Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";

import { ESTEDAD_FAMILY } from "../fonts";
import { watermarkLayoutConfig } from "../layout";
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
  readonly plan?: readonly { zone: string; startSeconds: number; endSeconds: number; rect: { x: number; y: number; w: number; h: number }; transition: string }[];
  readonly measurement?: { widthPx: number; heightPx: number; layout: "single-line" | "two-line"; measured: true };
  readonly color?: string;
}

/** Base shadow, always present so the mark is legible over bright footage. */
const BASE_TEXT_SHADOW = "0px 2px 6px rgba(0,0,0,0.85)";

const BLOOM_FRAMES = 60;
const DECAY_FRAMES = 60;
const QUIET_OPACITY = 0.6;
const BLOOM_SCALE = 1.15;

/**
 * Opening blackout for the watermark, in frames at the composition fps.
 *
 * 45 frames is 1.5s at 30fps: the opening moment owns the first impression
 * alone and the mark fades in after it has landed. The fade itself is
 * `INTRO_FADE_FRAMES` so the appearance never pops.
 */
const INTRO_HIDDEN_FRAMES = 45;
const INTRO_FADE_FRAMES = 15;

export const PersianWatermarkMark: React.FC<PersianWatermarkProps> = ({
  format,
  watermark = DEFAULT_WATERMARK,
  plan,
  measurement,
  color,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const typography = TYPOGRAPHY[format];

  // An empty lockup paints nothing. Without this guard the separator span
  // below renders a lone "|" that fades and migrates through all five phases —
  // a thin vertical line drifting across the frame with no text attached.
  if (!watermark.persianText && !watermark.latinText) return null;

  // V2 owns the watermark lifecycle. An explicitly empty plan is a measured,
  // intentional hide (never fall through to Legacy's five-phase animation).
  if (plan !== undefined && plan.length === 0) return null;
  if (plan && plan.length > 0) {
    const current = plan.find((entry) => frame / fps >= entry.startSeconds && frame / fps < entry.endSeconds) ?? plan[plan.length - 1];
    const previous = plan.findIndex((entry) => entry === current);
    const local = Math.max(0, Math.min(1, (frame / fps - current.startSeconds) / Math.max(0.01, current.endSeconds - current.startSeconds)));
    const transitionSeconds = 0.25;
    const elapsedSeconds = Math.max(0, frame / fps - current.startSeconds);
    const remainingSeconds = Math.max(0, current.endSeconds - frame / fps);
    const fade = Math.min(1, elapsedSeconds / transitionSeconds, remainingSeconds / transitionSeconds);
    const x = current.rect.x * 100;
    const y = current.rect.y * 100;
    const twoLine = measurement?.layout === "two-line";
    const config = watermarkLayoutConfig(format);
    return <div data-persian-watermark="v2" data-persian-watermark-zone={current.zone} data-persian-watermark-measured={measurement?.measured ? "true" : "false"} style={{position: "absolute", left: `${x}%`, top: `${y}%`, opacity: fade, display: "flex", flexDirection: twoLine ? "column" : "row", alignItems: "flex-start", direction: config.direction, gap: config.gapPx, fontFamily: ESTEDAD_FAMILY, fontWeight: config.weight, fontSize: config.fontSizePx, lineHeight: config.lineHeight, padding: config.paddingPx, color: color ?? PERSIAN_PALETTE.ink, textShadow: BASE_TEXT_SHADOW, whiteSpace: "nowrap", pointerEvents: "none", zIndex: 5}}><span dir="rtl">{watermark.persianText}</span>{twoLine ? null : <span aria-hidden="true" style={{opacity: 0.6}}>|</span>}<span dir="ltr">{watermark.latinText}</span></div>;
  }

  // Phase 0: hidden opening. Returning null paints nothing at all, which is
  // what "no watermark at the start" means — opacity 0 would still leave the
  // element in the tree for the whole opening.
  if (frame < INTRO_HIDDEN_FRAMES) return null;

  const introFadeEnd = INTRO_HIDDEN_FRAMES + INTRO_FADE_FRAMES;
  const quietEnd = Math.floor(durationInFrames * 0.2);
  const bloomEnd = quietEnd + BLOOM_FRAMES;
  const decayEnd = bloomEnd + DECAY_FRAMES;

  // On a clip too short to contain all phases, the ranges below would not
  // be strictly increasing and `interpolate` throws. Collapsing to the quiet
  // state is the honest fallback: there is no room for a bloom.
  const hasRoomForPhases = durationInFrames > decayEnd + 30;
  const hasRoomForIntroFade = quietEnd > introFadeEnd;

  const opacity = (() => {
    if (hasRoomForPhases && hasRoomForIntroFade) {
      return interpolate(
        frame,
        [INTRO_HIDDEN_FRAMES, introFadeEnd, quietEnd, bloomEnd, decayEnd],
        [0, QUIET_OPACITY, QUIET_OPACITY, 1, QUIET_OPACITY],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
    }
    if (hasRoomForIntroFade) {
      return interpolate(
        frame,
        [INTRO_HIDDEN_FRAMES, introFadeEnd],
        [0, QUIET_OPACITY],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
      );
    }
    return QUIET_OPACITY;
  })();

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

  // Both positions come from the tokens, which derive the quiet one from the moment
  // zone. See `computeWatermarkQuietTopPct` for why it cannot be a constant.
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
        color: PERSIAN_PALETTE.ink,
        textShadow: shadows.join(", "),
        whiteSpace: "nowrap",
        pointerEvents: "none",
        // Above footage and moments, below nothing — the mark is never covered.
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
