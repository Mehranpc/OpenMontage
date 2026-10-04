/** Music bed level under narration (#387).
 *
 * The bed ducks against real narration timing only. Inside the narrated span a pause
 * may lift the bed a little, never back to the full intro/outro level: on the
 * 2026-10-04 run a 0.94s pause at 7s jumped the bed from 0.148 to 0.72 (+13.7 dB) in
 * 0.28s and fell back when the voice resumed, which reads as a broken mix.
 * Full `base` level is reserved for before the first word and after the last.
 */
export type SpeechInterval = {readonly startSeconds: number; readonly endSeconds: number};
export type MusicLevels = {readonly base: number; readonly duck: number};

/** Largest lift a pause inside narration may give the bed: +6 dB over the duck level. */
export const MUSIC_PAUSE_LIFT = 2.0;
export const MUSIC_ATTACK_SECONDS = 0.35;
export const MUSIC_RELEASE_SECONDS = 0.9;

const smooth = (t: number) => {
  const x = Math.min(1, Math.max(0, t));
  return x * x * (3 - 2 * x);
};

export function musicLevelAt(seconds: number, intervals: readonly SpeechInterval[], levels: MusicLevels): number {
  if (!intervals.length) return levels.base;
  const first = intervals[0].startSeconds;
  const last = intervals[intervals.length - 1].endSeconds;
  const pause = Math.min(levels.base, levels.duck * MUSIC_PAUSE_LIFT);
  // Ceiling the bed may rise to at this instant, before the duck is applied.
  const ceiling = seconds < first || seconds > last ? levels.base : pause;
  let level = ceiling;
  for (const {startSeconds: start, endSeconds: end} of intervals) {
    if (seconds >= start && seconds <= end) return levels.duck;
    if (seconds >= start - MUSIC_ATTACK_SECONDS && seconds < start) {
      const top = start === first ? levels.base : pause;
      const t = smooth((seconds - (start - MUSIC_ATTACK_SECONDS)) / MUSIC_ATTACK_SECONDS);
      level = Math.min(level, top + (levels.duck - top) * t);
    } else if (seconds > end && seconds <= end + MUSIC_RELEASE_SECONDS) {
      const top = end === last ? levels.base : pause;
      const t = smooth((seconds - end) / MUSIC_RELEASE_SECONDS);
      level = Math.min(level, levels.duck + (top - levels.duck) * t);
    }
  }
  return level;
}
