/**
 * Persian footage video — the composition root.
 *
 * Assembles, in strict back-to-front order:
 *
 *   1. **Footage or typographic plate** — one per shot, sequenced.
 *   2. **Audio** — narration at full level, music ducked beneath it.
 *   3. **Captions** — approved-script burned captions when enabled.
 *   4. **Moments** — higher-priority editorial typography.
 *   5. **Watermark** — always on top, never covered.
 *
 * ## Why the layer order is fixed rather than data-driven
 *
 * Every layer above has exactly one correct position relative to the others.
 * Moments must sit above footage or they are invisible; the watermark must sit
 * above moments or a tall moment hides the brand; the grade must sit above footage
 * but below text or it dims the text along with the picture. Making the order
 * configurable would only create ways to get it wrong.
 *
 * ## Caption / moment interaction
 *
 * Burned captions are now allowed, but they are never authored independently. They
 * are derived from the same approved-script alignment that writes the sidecar SRT.
 * A caption component checks the absolute timeline against `moments` and paints
 * nothing while a moment is active. That makes two competing text layers impossible
 * on a frame even when their source timing windows overlap. The retired authored
 * `cues` and `hookText` shapes remain invalid.
 *
 * ## Timing
 *
 * All timings arrive in seconds and are converted to frames here, once. Each
 * moment and shot is wrapped in a `<Sequence>` whose `from`/`durationInFrames`
 * come from that conversion, so a component's local `useCurrentFrame()` is zero at
 * its own start. That is what lets the animation helpers take a plain start frame
 * instead of every component doing its own offset arithmetic — and offset
 * arithmetic repeated per component is where frame drift creeps in.
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
import { PersianCaptionBlock } from "./components/PersianCaptionBlock";
import { assertCaptionsFit } from "./captionLayout";
import { PersianMomentBlock } from "./components/PersianMomentBlock";
import { PersianV2MomentBlock } from "./v2/PersianV2MomentBlock";
import { isFilmType, prepareFilmTypeProps } from "./filmType/layout";
import { PersianFilmTypeMoment, PersianFilmTypeWatermark } from "./filmType/components";
import { PersianTypographicPlate } from "./components/PersianTypographicPlate";
import { PersianWatermarkMark } from "./components/PersianWatermarkMark";
import { estedadReady } from "./fonts";
import {
  FORMAT_DIMENSIONS,
  MOMENT_MIN_GAP_SECONDS,
  OPENING_MOMENT_MAX_START_SECONDS,
} from "./tokens";
import {
  DEFAULT_AUDIO_LEVELS,
  DEFAULT_WATERMARK,
  type PersianMoment,
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
 * Refuse a moment list that overlaps or crowds, at render time.
 *
 * The gap floor is the token that makes this pipeline's output structurally
 * different from a caption track, so it is enforced where it cannot be bypassed
 * rather than only advised in a skill. An overlap is worse than a crowded gap and
 * is reported first: two moments painting at once puts two right-anchored stacks
 * on the same rows, which is unreadable rather than merely rushed.
 *
 * A tolerance of one frame is allowed on the gap, because seconds-to-frames
 * rounding can shave a hair off a gap that was authored at exactly the floor, and
 * failing a render over 33ms of rounding would be noise.
 */
export function assertMomentsArePaced(
  moments: readonly PersianMoment[],
  fps: number,
): void {
  if (moments.length === 0) return;

  const ordered = [...moments].sort((a, b) => a.startSeconds - b.startSeconds);

  // The opening rule, enforced on this side of the boundary too — the same
  // single-rule-in-two-places pattern as the gap floor below. The pipeline gates
  // it at compose time; the renderer gates it at mount time, because props can
  // also reach a render by hand or from a fixture, and the opening is the one
  // moment where nothing on screen is a blank first impression on a muted feed.
  const first = ordered[0];
  if (first.startSeconds > OPENING_MOMENT_MAX_START_SECONDS + 1 / fps) {
    throw new Error(
      `The first moment (${first.id}) starts at ${first.startSeconds.toFixed(2)}s, ` +
        `past the ${OPENING_MOMENT_MAX_START_SECONDS}s opening deadline. Short-form ` +
        `feeds autoplay muted: a video that opens on silent footage has nothing on ` +
        `screen to hold a thumb. Fix the timing upstream.`,
    );
  }

  const tolerance = 1 / fps;
  for (let i = 1; i < ordered.length; i += 1) {
    const previous = ordered[i - 1];
    const current = ordered[i];
    const gap = current.startSeconds - previous.endSeconds;
    if (gap < 0) {
      throw new Error(
        `Moments ${previous.id} and ${current.id} overlap by ${(-gap).toFixed(2)}s. ` +
          `Two moments painting at once stack two right-anchored blocks on the same ` +
          `rows. Fix the timing upstream.`,
      );
    }
    if (gap < MOMENT_MIN_GAP_SECONDS - tolerance) {
      throw new Error(
        `Moments ${previous.id} and ${current.id} are only ${gap.toFixed(2)}s apart, ` +
          `below the ${MOMENT_MIN_GAP_SECONDS}s floor. Without that gap the moments ` +
          `read as a caption track rather than as deliberate typography, which is the ` +
          `specific outcome this model exists to prevent.`,
      );
    }
  }
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
  assertCaptionsFit(
    props.format ?? "vertical",
    props.captions ?? [],
    props.durationSeconds,
    props.design,
  );

  return {
    durationInFrames: Math.max(1, Math.round(props.durationSeconds * PERSIAN_FPS)),
    fps: PERSIAN_FPS,
    width: dimensions.width,
    height: dimensions.height,
    ...(isFilmType(props.design) ? { props: await prepareFilmTypeProps(props) } : {}),
  };
};

export const PersianFootageVideo: React.FC<PersianVideoProps> = ({
  format = "vertical",
  shots,
  moments,
  typographicBeats,
  captionMode,
  captions,
  audio,
  watermark = DEFAULT_WATERMARK,
  design,
  watermarkPlan,
  watermarkMeasurement,
  filmType,
}) => {
  const v2WatermarkColor = design?.version === 2
    ? ((design.resolved as any)?.typography?.ink ?? "#F0EDE6")
    : undefined;
  const { fps, durationInFrames } = useVideoConfig();
  const filmTypeEnabled = isFilmType(design);
  if (filmTypeEnabled && !filmType) throw new Error("Film Type needs its measured props; run persian_compose or calculatePersianMetadata before mounting the component.");

  const toFrames = React.useCallback(
    (seconds: number) => Math.round(seconds * fps),
    [fps],
  );

  assertMomentsArePaced(moments, fps);
  if (captionMode === "sidecar_only" && captions.length > 0) {
    throw new Error("sidecar_only captionMode cannot paint burned captions");
  }

  const musicVolume = React.useMemo(() => {
    const levels = {
      flat: audio?.musicFlatVolume ?? DEFAULT_AUDIO_LEVELS.musicFlatVolume,
      base: audio?.musicBaseVolume ?? DEFAULT_AUDIO_LEVELS.musicBaseVolume,
      duck: audio?.musicDuckVolume ?? DEFAULT_AUDIO_LEVELS.musicDuckVolume,
    };

    // With no narration the music carries the piece alone, so it sits at a flat,
    // slightly lower level — a bed mixed for speech sounds thin without it.
    if (!audio?.narration) return () => levels.flat;

    // Duck only against real narration timing. Captions and editorial moments are
    // visual systems and must never drive the mix. Short attack/release ramps avoid
    // audible pumping while still letting the bed breathe in genuine speech pauses.
    const intervals = audio?.speechIntervals ?? [];
    const attack = 0.18, release = 0.28;
    return (frame: number) => {
      const seconds = frame / fps;
      let level = levels.base;
      for (const interval of intervals) {
        const start = interval.startSeconds, end = interval.endSeconds;
        if (seconds >= start && seconds <= end) level = Math.min(level, levels.duck);
        else if (seconds >= start - attack && seconds < start) {
          const t = (seconds - (start - attack)) / attack;
          level = Math.min(level, levels.base + (levels.duck - levels.base) * t);
        } else if (seconds > end && seconds <= end + release) {
          const t = (seconds - end) / release;
          level = Math.min(level, levels.duck + (levels.base - levels.duck) * t);
        }
      }
      const fadeSeconds = audio?.musicFadeSeconds ?? DEFAULT_AUDIO_LEVELS.musicFadeSeconds;
      const totalSeconds = durationInFrames / fps;
      const head = fadeSeconds > 0 ? Math.min(1, seconds / fadeSeconds) : 1;
      const tail = fadeSeconds > 0 ? Math.min(1, Math.max(0, totalSeconds - seconds) / fadeSeconds) : 1;
      return level * Math.min(head, tail);
    };
  }, [audio, fps, durationInFrames]);

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
              showGrade={!filmTypeEnabled}
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
             the level it was recorded, and the music sits beneath it. */}
      {audio?.narration ? <Audio src={resolveSrc(audio.narration)} /> : null}
      {audio?.music ? (
        <Audio src={resolveSrc(audio.music)} loop volume={musicVolume} />
      ) : null}

      {/* 3. Burned captions. They are runtime-derived from approved script text,
          never from ASR spelling. PersianCaptionBlock suppresses itself whenever an
          editorial moment owns the frame, so the two text systems cannot compete. */}
      {captionMode !== "sidecar_only"
        ? captions.map((caption) => {
            const from = toFrames(caption.startSeconds);
            const duration = Math.max(1, toFrames(caption.endSeconds) - from);
            return (
              <Sequence
                key={caption.id}
                from={from}
                durationInFrames={duration}
                layout="none"
              >
                <PersianCaptionBlock
                  caption={caption}
                  format={format}
                  moments={moments}
                  design={design}
                />
              </Sequence>
            );
          })
        : null}

      {/* 4. Moments. `layout="none"` so the sequence introduces no positioned
             wrapper — each moment positions itself against the frame. */}
      {moments.map((moment) => {
        const from = toFrames(moment.startSeconds);
        const duration = Math.max(1, toFrames(moment.endSeconds) - from);
        return (
          <Sequence
            key={moment.id}
            from={from}
            durationInFrames={duration}
            layout="none"
          >
            {design ? (
              design.version === 2 ? (
                filmTypeEnabled ? (
                  <PersianFilmTypeMoment moment={moment} layout={filmType!.moments[moment.id]} format={format} durationFrames={duration} design={design} shots={shots} />
                ) : <PersianV2MomentBlock moment={moment} format={format} durationFrames={duration} design={design} />
              ) : (() => { throw new Error(`Unsupported Persian design snapshot version: ${String(design.version)}`); })()
            ) : (
              <PersianMomentBlock moment={moment} format={format} durationFrames={duration} />
            )}
          </Sequence>
        );
      })}

      {/* 5. Watermark, above everything. */}
      {filmTypeEnabled ? (
        <PersianFilmTypeWatermark format={format} design={design!} lockup={filmType!.lockup} plan={watermarkPlan} />
      ) : <PersianWatermarkMark format={format} watermark={watermark} plan={design?.version === 2 ? watermarkPlan : undefined} measurement={design?.version === 2 ? watermarkMeasurement : undefined} color={v2WatermarkColor} />}

      {/* Safe-area and zone guides are intentionally NOT rendered — they exist in
          tokens for layout math only. A debug guide that ships is worse than no
          guide. `durationInFrames` is read here so the paced-moments check above
          cannot be dropped as unused by a future refactor. */}
      <span style={{ display: "none" }} data-total-frames={durationInFrames} />
    </AbsoluteFill>
  );
};
