/**
 * Typographic beat — a cue with no footage behind it.
 *
 * Exists so the pipeline never has to choose between a wrong clip and a gap. Some
 * ideas have no honest stock footage, and searching harder produces a clip that
 * contradicts the narration, which is worse than no clip at all. The asset
 * director caps how many of these a video may contain.
 *
 * ## Why it still moves
 *
 * A static dark frame in the middle of a montage reads as a playback stall. The
 * motion here comes entirely from the *background* — drifting orbs and a light
 * sweep — because the text on top is settled and settled text must not be
 * transformed (see `motion.ts`). So the beat feels alive while the type stays
 * geometrically still.
 *
 * ## Why the orbs are seeded, not random
 *
 * `mulberry32` produces the same sequence for the same seed, so each orb keeps
 * its position across every frame and every render worker. `Math.random()` here
 * would reposition them per frame and per worker — the result looks like static,
 * and it would differ between a local render and a distributed one.
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { PERSIAN_PALETTE, type PersianFormat } from "../tokens";

export interface PersianTypographicPlateProps {
  readonly format: PersianFormat;
  /** Stable seed, so the same beat looks identical on re-render. */
  readonly seed: number;
}

/**
 * Deterministic PRNG. Small, fast, and — the only property that matters here —
 * reproducible from an integer seed.
 */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const ORB_COUNT = 5;

interface Orb {
  readonly xPct: number;
  readonly yPct: number;
  readonly radiusPct: number;
  readonly alpha: number;
  /** Drift period in frames — an integer, so the loop is seamless. */
  readonly periodFrames: number;
  readonly phase: number;
  readonly color: string;
}

function buildOrbs(seed: number): Orb[] {
  const random = mulberry32(seed);
  const colors = ["#3A1772", "#1789FC", "#004FFF", "#2C2C2C", "#3A1772"];
  return Array.from({ length: ORB_COUNT }, (_, index) => ({
    // Edge-biased: orbs near the centre wash out the text they sit behind, so
    // they are pushed toward the frame edges where they read as ambient light.
    xPct: random() < 0.5 ? random() * 30 : 70 + random() * 30,
    yPct: random() * 100,
    radiusPct: 45 + random() * 35,
    // Very low alpha. These are meant to be felt, not seen; anything above ~0.08
    // becomes a visible blob and starts competing with the type.
    alpha: 0.02 + random() * 0.04,
    // Integer periods so `frame % period` returns to 0 exactly and the drift
    // never jumps at the loop point.
    periodFrames: 240 + Math.floor(random() * 240),
    phase: random(),
    color: colors[index % colors.length],
  }));
}

export const PersianTypographicPlate: React.FC<PersianTypographicPlateProps> = ({
  format,
  seed,
}) => {
  const frame = useCurrentFrame();
  const orbs = React.useMemo(() => buildOrbs(seed), [seed]);

  return (
    <AbsoluteFill style={{ backgroundColor: PERSIAN_PALETTE.voidBackground }}>
      {/* Rendered oversized and offset, so the orbs can drift without their
          edges ever entering the frame. */}
      <AbsoluteFill
        style={{
          width: "140%",
          height: "140%",
          left: "-20%",
          top: "-20%",
          position: "absolute",
        }}
      >
        {orbs.map((orb, index) => {
          const t = ((frame / orb.periodFrames + orb.phase) % 1) * Math.PI * 2;
          const driftX = Math.cos(t) * 3;
          const driftY = Math.sin(t) * 3;
          return (
            <div
              key={index}
              style={{
                position: "absolute",
                left: `${orb.xPct + driftX}%`,
                top: `${orb.yPct + driftY}%`,
                width: `${orb.radiusPct}%`,
                height: `${orb.radiusPct}%`,
                transform: "translate(-50%, -50%)",
                borderRadius: "50%",
                background: `radial-gradient(circle, ${orb.color}${Math.round(
                  orb.alpha * 255,
                )
                  .toString(16)
                  .padStart(2, "0")} 0%, rgba(0,0,0,0) 70%)`,
              }}
            />
          );
        })}
      </AbsoluteFill>

      {/* Static film grain. The seed and octave count are constants: a
          per-frame-varying seed is television static, not grain. */}
      <AbsoluteFill style={{ opacity: 0.08, pointerEvents: "none" }}>
        <svg width="100%" height="100%">
          <filter id={`persian-grain-${format}`}>
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.55"
              numOctaves="2"
              seed="11"
              stitchTiles="stitch"
            />
          </filter>
          <rect
            width="100%"
            height="100%"
            filter={`url(#persian-grain-${format})`}
          />
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
