/**
 * Motion grammar for the Persian composition.
 *
 * Ported in principle (not copied wholesale) from the motion system in
 * `youtube-videos`, whose central insight is that every animated value should be
 * a pure `frame → value` function. Nothing here holds state, so any frame can be
 * rendered independently — which is what makes a distributed Remotion render
 * produce the same bytes as a sequential one.
 *
 * ## The rule that governs everything below
 *
 * **Settled text must never be transformed.** Once a word has arrived, it may
 * change only in glow alpha and brightness. It may not scale, translate, or
 * rotate, even imperceptibly. A sub-pixel transform on a glyph forces the
 * rasterizer to re-snap its outlines to the pixel grid every frame, and the
 * result is a visible shimmer along the letter edges — worst on Persian, whose
 * connecting strokes are thin, horizontal, and run the full width of a word.
 *
 * Held beats still need life, or the video looks frozen. That life comes from
 * the *room* — the background plate drifting, the light lobes panning — never
 * from the type. `holdLife` returns only the two channels text is allowed to use.
 */

import { Easing, interpolate, spring } from "remotion";

/** Named spring weights. Heavier subject ⇒ more mass, less stiffness. */
export const SPRING_WEIGHTS = {
  /** Hook lines, hero typographic beats. Slow, deliberate arrival. */
  hero: { damping: 18, stiffness: 110, mass: 1.4 },
  /** Subtitle words, most body text. The default. */
  standard: { damping: 16, stiffness: 130, mass: 1 },
  /** Small labels, watermark. Quick, unobtrusive. */
  light: { damping: 20, stiffness: 220, mass: 0.7 },
  /** Over-damped so an exit never overshoots back into frame. */
  exit: { damping: 30, stiffness: 200, mass: 1 },
} as const;

export type SpringWeight = keyof typeof SPRING_WEIGHTS;

/**
 * Per-weight entrance geometry.
 *
 * `travelPx` is downward travel *toward* the settled position, so text rises
 * into place — the direction that reads as "arriving" rather than "dropping".
 * `blurPx` de-focuses only during arrival; it is 0 by the time the word settles,
 * because a permanent blur on Persian thins the joining strokes to nothing.
 */
const ENTER_SPEC: Record<SpringWeight, { travelPx: number; fromScale: number; blurPx: number }> = {
  hero: { travelPx: 26, fromScale: 0.94, blurPx: 8 },
  standard: { travelPx: 18, fromScale: 0.96, blurPx: 6 },
  light: { travelPx: 12, fromScale: 0.975, blurPx: 0 },
  exit: { travelPx: 12, fromScale: 0.98, blurPx: 0 },
};

/** Frames an entrance takes. Inside the 9–15 band that reads as deliberate. */
export const ENTER_FRAMES = 13;
/** Frames an exit takes. Exits are faster than entrances — nobody watches them. */
export const EXIT_FRAMES = 8;

export interface MaterialTransform {
  readonly opacity: number;
  readonly scale: number;
  readonly translateYPx: number;
  readonly blurPx: number;
  /** Ready-made CSS `transform`, so callers cannot forget the unit. */
  readonly transform: string;
  /** Ready-made CSS `filter`, or undefined when no blur applies. */
  readonly filter: string | undefined;
}

const SETTLED: MaterialTransform = {
  opacity: 1,
  scale: 1,
  translateYPx: 0,
  blurPx: 0,
  transform: "none",
  filter: undefined,
};

function toTransform(scale: number, translateYPx: number): string {
  // `translate3d` keeps the element on its own compositing layer during the
  // animation. Once settled, callers get `transform: "none"` instead, which
  // drops the layer so the glyphs rasterize against the pixel grid exactly once.
  return `translate3d(0, ${translateYPx.toFixed(3)}px, 0) scale(${scale.toFixed(5)})`;
}

/**
 * Appearance animation. Returns the settled state exactly once the entrance is
 * over, so a settled element carries no transform at all.
 *
 * @param frame Current frame, absolute.
 * @param startFrame Frame at which this element begins arriving.
 */
export function materialEnter(
  frame: number,
  startFrame: number,
  fps: number,
  weight: SpringWeight = "standard",
): MaterialTransform {
  const local = frame - startFrame;
  if (local >= ENTER_FRAMES) return SETTLED;
  if (local < 0) {
    const spec = ENTER_SPEC[weight];
    return {
      opacity: 0,
      scale: spec.fromScale,
      translateYPx: spec.travelPx,
      blurPx: spec.blurPx,
      transform: toTransform(spec.fromScale, spec.travelPx),
      filter: spec.blurPx > 0 ? `blur(${spec.blurPx}px)` : undefined,
    };
  }

  const spec = ENTER_SPEC[weight];
  const progress = spring({
    frame: local,
    fps,
    config: SPRING_WEIGHTS[weight],
    durationInFrames: ENTER_FRAMES,
  });

  const opacity = interpolate(progress, [0, 1], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = interpolate(progress, [0, 1], [spec.fromScale, 1]);
  const translateYPx = interpolate(progress, [0, 1], [spec.travelPx, 0]);
  // Blur clears at 60% of the arrival so the glyphs are already crisp while the
  // last of the motion resolves. Clearing it at the very end reads as softness.
  const blurPx = interpolate(progress, [0, 0.6], [spec.blurPx, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return {
    opacity,
    scale,
    translateYPx,
    blurPx,
    transform: toTransform(scale, translateYPx),
    filter: blurPx > 0.05 ? `blur(${blurPx.toFixed(2)}px)` : undefined,
  };
}

/**
 * Disappearance animation — faster than an entrance, no blur, no overshoot.
 *
 * @param endFrame Frame at which the element must be fully gone.
 */
export function materialExit(
  frame: number,
  endFrame: number,
  fps: number,
  weight: SpringWeight = "standard",
): MaterialTransform {
  const startFrame = endFrame - EXIT_FRAMES;
  if (frame <= startFrame) return SETTLED;

  const local = Math.min(frame - startFrame, EXIT_FRAMES);
  const spec = ENTER_SPEC[weight];
  const progress = spring({
    frame: local,
    fps,
    config: SPRING_WEIGHTS.exit,
    durationInFrames: EXIT_FRAMES,
  });

  const opacity = interpolate(progress, [0, 1], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // Exits travel a shorter distance and in the same direction as arrival, so the
  // element leaves the way it came instead of appearing to be pushed.
  const travel = spec.travelPx * 0.5;
  const scale = interpolate(progress, [0, 1], [1, spec.fromScale]);
  const translateYPx = interpolate(progress, [0, 1], [0, travel]);

  return {
    opacity,
    scale,
    translateYPx,
    blurPx: 0,
    transform: toTransform(scale, translateYPx),
    filter: undefined,
  };
}

export interface HoldLife {
  /** 0–1 multiplier for a glow's alpha. Safe on text. */
  readonly glowAlpha: number;
  /** CSS `filter: brightness()` value, near 1. Safe on text. */
  readonly brightness: number;
}

/**
 * The only animation a settled element may receive.
 *
 * Both channels are compositing-only: they change how existing pixels are tinted
 * without moving a glyph outline, so the rasterizer never re-snaps and no edge
 * shimmer appears. Periods are co-prime-ish and expressed in frames so the two
 * channels drift against each other and the loop never becomes obvious.
 *
 * @param seedOffset Per-element phase offset so neighbours do not pulse in sync.
 */
export function holdLife(frame: number, seedOffset = 0): HoldLife {
  const glowPeriod = 88;
  const brightnessPeriod = 84;
  const phase = frame + seedOffset;

  // Triangle waves rather than sines: a sine spends most of its time near the
  // extremes, so slow sinusoidal motion appears to stall at the turnarounds. A
  // triangle has constant slope, so the movement reads as continuous.
  const triangle = (period: number): number => {
    const t = ((phase % period) + period) % period;
    const half = period / 2;
    return t < half ? t / half : 2 - t / half;
  };

  return {
    glowAlpha: 0.78 + 0.22 * triangle(glowPeriod),
    brightness: 1 + 0.07 * (triangle(brightnessPeriod) - 0.5),
  };
}

/**
 * A layered text glow, as two stacked shadows.
 *
 * One tight shadow reads as a hard edge and one wide shadow reads as a haze;
 * together they suggest a light source rather than an outline. A single shadow
 * at any radius reads as a sticker.
 */
export function glow(hexColor: string, radiusPx: number, alpha: number): string {
  const rgb = hexToRgb(hexColor);
  const inner = `0 0 ${(radiusPx * 0.45).toFixed(1)}px rgba(${rgb}, ${(alpha * 0.9).toFixed(3)})`;
  const outer = `0 0 ${radiusPx.toFixed(1)}px rgba(${rgb}, ${(alpha * 0.5).toFixed(3)})`;
  return `${inner}, ${outer}`;
}

function hexToRgb(hex: string): string {
  const clean = hex.replace("#", "");
  const full =
    clean.length === 3
      ? clean.split("").map((c) => c + c).join("")
      : clean;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `${r}, ${g}, ${b}`;
}

/** Camera moves available to footage. Never applied over bare text. */
export type CameraMove =
  | "push-in"
  | "pull-out"
  | "pan-left"
  | "pan-right"
  | "none";

export interface CameraState {
  readonly scale: number;
  readonly translateXPct: number;
  readonly transform: string;
}

/**
 * A slow camera move that decelerates into a static tail.
 *
 * The tail matters: a move still running when a cut arrives makes the cut feel
 * like a stumble, because the eye is tracking motion that vanishes. Ending on
 * held frames lets the viewer settle before the change.
 *
 * `amount` is small by design. Stock footage is already photographed with its own
 * motion; a large synthetic move on top reads as a slideshow effect.
 */
export function cameraMove(
  frame: number,
  durationInFrames: number,
  move: CameraMove,
  amount = 0.04,
): CameraState {
  const still: CameraState = { scale: 1, translateXPct: 0, transform: "none" };
  if (move === "none" || durationInFrames <= 0) return still;

  // Reserve the last 20% (max 18 frames) as a static tail.
  const tail = Math.min(18, Math.floor(durationInFrames * 0.2));
  const active = Math.max(1, durationInFrames - tail);
  const progress = interpolate(frame, [0, active], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  switch (move) {
    case "push-in": {
      const scale = 1 + amount * progress;
      return { scale, translateXPct: 0, transform: `scale(${scale.toFixed(5)})` };
    }
    case "pull-out": {
      const scale = 1 + amount - amount * progress;
      return { scale, translateXPct: 0, transform: `scale(${scale.toFixed(5)})` };
    }
    case "pan-left":
    case "pan-right": {
      // A pan must be paired with an overscale, or the frame edge slides into
      // view as a black bar. The scale is derived from the pan distance so the
      // two can never be configured inconsistently.
      const scale = 1 + amount * 2;
      const span = amount * 100;
      const direction = move === "pan-left" ? -1 : 1;
      const translateXPct = direction * span * (progress - 0.5);
      return {
        scale,
        translateXPct,
        transform: `scale(${scale.toFixed(5)}) translateX(${translateXPct.toFixed(3)}%)`,
      };
    }
    default:
      return still;
  }
}

/** Stagger between successive items, in frames. */
export const STAGGER = {
  /** Words inside one subtitle line. */
  word: 2,
  /** Items in a list. */
  item: 4,
  /** Distinct hierarchy levels (title vs body). */
  block: 7,
} as const;

/** Cap on total stagger, so a long line's last word is never left behind. */
export const MAX_STAGGER_FRAMES = 10;

/**
 * Stagger delay for item `index`, clamped so a long line stays in sync with its
 * own cue timing. Without the clamp, a ten-word line would still be arriving
 * twenty frames after the cue began — by which point the audio has moved on.
 */
export function staggerDelay(index: number, step: number = STAGGER.word): number {
  return Math.min(index * step, MAX_STAGGER_FRAMES);
}
