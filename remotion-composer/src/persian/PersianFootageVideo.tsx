/**
 * Persian footage video — the composition root.
 *
 * Assembles, in strict back-to-front order:
 *
 *   1. **Footage or typographic plate** — one per shot, sequenced.
 *   2. **Audio** — narration at full level, music ducked beneath it.
 *   3. **Hook** — the opening title line, if any.
 *   4. **Subtitles** — one glass panel per cue.
 *   5. **Watermark** — always on top, never covered.
 *
 * ## Why the layer order is fixed rather than data-driven
 *
 * Every layer above has exactly one correct position relative to the others.
 * Subtitles must sit above footage or they are invisible; the watermark must sit
 * above subtitles or a long cue hides the brand; the grade must sit above footage
 * but below text or it dims the text along with the picture. Making the order
 * configurable would only create ways to get it wrong.
 *
 * ## Timing
 *
 * All timings arrive in seconds and are converted to frames here, once. Each cue
 * and shot is wrapped in a `<Sequence>` whose `from`/`durationInFrames` come from
 * that conversion, so a component's local `useCurrentFrame()` is zero at its own
 * start. That is what lets the animation helpers take a plain start frame instead
 * of every component doing its own offset arithmetic — and offset arithmetic
 * repeated per component is where frame drift creeps in.
 */

import React from "react";
import {
  AbsoluteFill,
  Audio,
  CalculateMetadataFunction,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";

import { PersianFootageLayer } from "./components/PersianFootageLayer";
import { PersianHook } from "./components/PersianHook";
import { PersianSubtitleBlock } from "./components/PersianSubtitleBlock";
import { PersianTypographicPlate } from "./components/PersianTypographicPlate";
import { PersianWatermarkMark } from "./components/PersianWatermarkMark";
import { estedadReady } from "./fonts";
import { FORMAT_DIMENSIONS, TYPOGRAPHY } from "./tokens";
import {
  DEFAULT_AUDIO_LEVELS,
  DEFAULT_WATERMARK,
  type PersianVideoProps,
} from "./types";

/** Frames per second for every Persian composition. Matches the rest of the repo. */
export const PERSIAN_FPS = 30;

/**
 * Resolve an asset path to a URL Remotion can load.
 *
 * A path already absolute (`http`, `file`, or a leading `/`) is passed through;
 * anything else is treated as relative to the composition's public dir. This lets
 * the pipeline hand over either a downloaded clip inside `public/` or an absolute
 * path to a cached asset elsewhere, without the props needing a discriminator.
 */
function resolveSrc(path: string): string {
  if (/^(https?:|file:|\/)/.test(path)) return path;
  return staticFile(path);
}

/**
 * Duration comes from props rather than being derived from the shots.
 *
 * Deriving it would make the video length depend on whether the last shot's
 * `endSeconds` happened to include the tail — a fragile coupling. The pipeline
 * knows the intended duration (a 60-second brief means 60 seconds) and states it.
 */
export const calculatePersianMetadata: CalculateMetadataFunction<
  PersianVideoProps
> = async ({ props }) => {
  const dimensions = FORMAT_DIMENSIONS[props.format ?? "vertical"];

  // Block metadata resolution on the font. `calculateMetadata` runs before the
  // component tree mounts, so awaiting here guarantees no measurement can happen
  // against a fallback face even on the very first frame Remotion renders — which
  // during a still or a thumbnail may not be frame 0.
  await estedadReady;

  return {
    durationInFrames: Math.max(1, Math.round(props.durationSeconds * PERSIAN_FPS)),
    fps: PERSIAN_FPS,
    width: dimensions.width,
    height: dimensions.height,
  };
};

export const PersianFootageVideo: React.FC<PersianVideoProps> = ({
  format = "vertical",
  shots,
  cues,
  typographicBeats,
  audio,
  watermark = DEFAULT_WATERMARK,
  hookText,
  hookDurationSeconds = 4,
}) => {
  const { fps, durationInFrames } = useVideoConfig();
  const typography = TYPOGRAPHY[format];

  const toFrames = React.useCallback(
    (seconds: number) => Math.round(seconds * fps),
    [fps],
  );

  const musicVolume = React.useMemo(() => {
    const levels = {
      flat: audio?.musicFlatVolume ?? DEFAULT_AUDIO_LEVELS.musicFlatVolume,
      base: audio?.musicBaseVolume ?? DEFAULT_AUDIO_LEVELS.musicBaseVolume,
      duck: audio?.musicDuckVolume ?? DEFAULT_AUDIO_LEVELS.musicDuckVolume,
    };

    // With no narration the music carries the piece alone, so it sits at a flat,
    // slightly lower level — a bed mixed for speech sounds thin without it.
    if (!audio?.narration) return () => levels.flat;

    // With narration, duck under every cue window. Built as a frame-indexed
    // lookup rather than a per-frame search over cues: the callback runs once per
    // frame per render worker, and a linear scan over cues there is wasted work.
    const ducked = new Uint8Array(Math.max(1, durationInFrames));
    for (const cue of cues) {
      const start = Math.max(0, toFrames(cue.startSeconds));
      const end = Math.min(ducked.length, toFrames(cue.endSeconds));
      for (let f = start; f < end; f += 1) ducked[f] = 1;
    }

    return (frame: number) => {
      const index = Math.min(Math.max(frame, 0), ducked.length - 1);
      return ducked[index] === 1 ? levels.duck : levels.base;
    };
  }, [audio, cues, durationInFrames, toFrames]);

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      {/* 1. Footage. Each shot owns its own sequence, so a shot's camera move is
             computed against its own duration rather than the whole timeline. */}
      {shots.map((shot) => {
        const from = toFrames(shot.startSeconds);
        const duration = Math.max(1, toFrames(shot.endSeconds) - from);
        return (
          <Sequence key={shot.id} from={from} durationInFrames={duration}>
            <PersianFootageLayer
              shot={shot}
              src={resolveSrc(shot.source)}
              durationFrames={duration}
            />
          </Sequence>
        );
      })}

      {/* Typographic beats sit in the same layer as footage — they are an
          alternative to footage for that stretch of time, not an overlay. */}
      {(typographicBeats ?? []).map((beat, index) => {
        const from = toFrames(beat.startSeconds);
        const duration = Math.max(1, toFrames(beat.endSeconds) - from);
        return (
          <Sequence key={beat.id} from={from} durationInFrames={duration}>
            <PersianTypographicPlate format={format} seed={index + 1} />
          </Sequence>
        );
      })}

      {/* 2. Audio. Narration is never ducked or processed here — it arrives at
             the level it was recorded, and the music moves around it. */}
      {audio?.narration ? (
        <Audio src={resolveSrc(audio.narration)} />
      ) : null}
      {audio?.music ? (
        <Audio src={resolveSrc(audio.music)} loop volume={musicVolume} />
      ) : null}

      {/* 3. Hook. */}
      {hookText ? (
        <Sequence from={0} durationInFrames={toFrames(hookDurationSeconds)}>
          <PersianHook
            text={hookText}
            format={format}
            durationFrames={toFrames(hookDurationSeconds)}
          />
        </Sequence>
      ) : null}

      {/* 4. Subtitles. `layout="none"` so the sequence does not introduce a
             positioned wrapper — the block positions itself against the frame. */}
      {cues.map((cue) => {
        const from = toFrames(cue.startSeconds);
        const duration = Math.max(1, toFrames(cue.endSeconds) - from);
        return (
          <Sequence
            key={cue.id}
            from={from}
            durationInFrames={duration}
            layout="none"
          >
            <PersianSubtitleBlock
              cue={cue}
              format={format}
              cueStartFrame={0}
              cueDurationFrames={duration}
            />
          </Sequence>
        );
      })}

      {/* 5. Watermark, above everything. */}
      <PersianWatermarkMark format={format} watermark={watermark} />

      {/* Bottom safe-area guide is intentionally NOT rendered — it exists in
          tokens for layout math only. Rendering it would put a debug artifact in
          the output, and a guide that ships is worse than no guide. */}
      <span style={{ display: "none" }} data-subtitle-bottom={typography.subtitleBottomPx} />
    </AbsoluteFill>
  );
};
