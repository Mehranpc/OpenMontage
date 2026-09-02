/**
 * Shared prop contract for the Persian composition.
 *
 * This is the boundary between the Python pipeline and the renderer, so it is
 * written as plain JSON-serializable data with no derived or optional-magic
 * fields: everything the composition needs is either present or has an explicit
 * default here, never inferred from a sibling field. Cross-field inference is
 * what makes a props file that validates still render wrong.
 *
 * Times are in **seconds** at this boundary (what a transcript and an SRT speak),
 * and converted to frames exactly once, inside the components. Mixing units
 * across the boundary is the most common source of off-by-one-frame drift.
 */

import type { CameraMove } from "./motion";
import type { PersianFormat } from "./tokens";

/** One word with its spoken window, from whisper word-level timestamps. */
export interface PersianWord {
  readonly text: string;
  readonly startSeconds: number;
  readonly endSeconds: number;
}

/**
 * One subtitle cue.
 *
 * `words` is optional: with it, karaoke emphasis tracks the voice; without it,
 * the cue animates in as a block with staggered word entrances. Both paths are
 * first-class — a video with no narration has no word timings and must still
 * look deliberate.
 */
export interface PersianCue {
  readonly id: string;
  readonly text: string;
  readonly startSeconds: number;
  readonly endSeconds: number;
  readonly words?: readonly PersianWord[];
  /**
   * Phrases to emphasise, matched against `text` by normalized comparison.
   * Multi-word phrases are treated as one unbreakable unit by the line breaker,
   * so an emphasis never straddles a line break.
   */
  readonly highlightPhrases?: readonly string[];
}

/**
 * One footage segment.
 *
 * `sourceUrl` is a `staticFile()`-relative path, not an absolute URL: the render
 * must not depend on network availability, and a remote fetch mid-render
 * produces intermittent black frames that only appear under concurrency.
 */
export interface PersianShot {
  readonly id: string;
  /** Path relative to the composition's public dir. */
  readonly source: string;
  /** Timeline position, seconds. */
  readonly startSeconds: number;
  readonly endSeconds: number;
  /** In-point within the source clip, seconds. */
  readonly sourceInSeconds: number;
  readonly camera: CameraMove;
  /**
   * Attribution string for the credits beat. Required by both Pexels' and
   * Pixabay's licence terms, so it is not optional in the type — a shot that
   * cannot be attributed should not be in the manifest.
   */
  readonly attribution: string;
}

/**
 * A cue with no footage behind it.
 *
 * Exists because some concepts have no honest stock clip, and a wrong clip is
 * worse than none. Capped upstream (the asset director enforces the cap) so this
 * cannot quietly become the whole video.
 */
export interface PersianTypographicBeat {
  readonly id: string;
  readonly startSeconds: number;
  readonly endSeconds: number;
}

export interface PersianAudio {
  /** Narration path relative to the public dir, if any. */
  readonly narration?: string;
  /** Music bed path relative to the public dir, if any. */
  readonly music?: string;
  /** Music level when narration is absent. */
  readonly musicFlatVolume?: number;
  /** Music level when narration is present but not speaking. */
  readonly musicBaseVolume?: number;
  /** Music level while narration speaks. */
  readonly musicDuckVolume?: number;
}

export interface PersianWatermark {
  /** Persian side of the lockup. Rendered in an explicit RTL span. */
  readonly persianText: string;
  /** Latin side of the lockup. Rendered in an explicit LTR span. */
  readonly latinText: string;
}

/**
 * Root props.
 *
 * Declared as a `type` alias rather than an `interface` deliberately: Remotion's
 * `CalculateMetadataFunction<T>` constrains `T` to `Record<string, unknown>`, and
 * TypeScript grants an implicit index signature to object-literal type aliases
 * but not to interfaces. The existing compositions in this repo (`TitledVideoProps`
 * and friends) use the same form for the same reason.
 */
export type PersianVideoProps = {
  readonly format: PersianFormat;
  readonly shots: readonly PersianShot[];
  readonly cues: readonly PersianCue[];
  readonly typographicBeats?: readonly PersianTypographicBeat[];
  readonly audio?: PersianAudio;
  readonly watermark?: PersianWatermark;
  /** Opening hook line. Absent means no hook beat. */
  readonly hookText?: string;
  readonly hookDurationSeconds?: number;
  /** Total duration. Authoritative — `calculateMetadata` uses it directly. */
  readonly durationSeconds: number;
};

/** The watermark the user specified for this pipeline. */
export const DEFAULT_WATERMARK: PersianWatermark = {
  persianText: "طریقت تسلیم",
  latinText: "@Pathway_of_Surrender",
};

export const DEFAULT_AUDIO_LEVELS = {
  musicFlatVolume: 0.5,
  musicBaseVolume: 0.6,
  musicDuckVolume: 0.36,
} as const;
