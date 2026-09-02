/**
 * Demo fixture for the Persian compositions.
 *
 * Its job is to make the Persian composition openable in Remotion Studio with no
 * pipeline run and no downloaded footage, so the typography can be inspected on
 * its own. `shots` is therefore empty and the whole runtime is typographic beats:
 * a fixture that referenced clip files would render black for anyone who has not
 * produced those files, which makes the studio preview useless exactly when it is
 * most needed.
 *
 * The text exercises the cases that break Persian rendering, deliberately:
 *   - ZWNJ words («می‌کند», «نمی‌شود», «هم‌زمان») — the measure-vs-paint split.
 *   - A proclitic and an enclitic near a likely break point — the break rules.
 *   - An explicit ezafe («تجربهٔ») — the no-break-after-ezafe rule.
 *   - Mixed Persian, Latin, and digits in one cue — bidi isolation.
 *   - A cue long enough to need three lines — the fitter.
 */

import type { PersianVideoProps } from "./types";
import { DEFAULT_WATERMARK } from "./types";

export const persianDemoFixture: PersianVideoProps = {
  format: "vertical",
  durationSeconds: 18,
  hookText: "این متن *فارسی* است",
  hookDurationSeconds: 3.5,
  shots: [],
  typographicBeats: [
    { id: "beat-1", startSeconds: 0, endSeconds: 9 },
    { id: "beat-2", startSeconds: 9, endSeconds: 18 },
  ],
  watermark: DEFAULT_WATERMARK,
  cues: [
    {
      id: "cue-1",
      startSeconds: 3.6,
      endSeconds: 7.2,
      text: "این جمله نشان می‌دهد که نیم‌فاصله درست رندر می‌شود",
      highlightPhrases: ["نیم‌فاصله"],
    },
    {
      id: "cue-2",
      startSeconds: 7.4,
      endSeconds: 11.5,
      // Long enough to force the line breaker to balance three lines, and
      // containing «به» and «را» where a greedy wrap would strand them.
      text: "شکستن خطِ فارسی باید به گونه‌ای باشد که هیچ حرف اضافه‌ای را تنها در پایان خط رها نکند",
      highlightPhrases: ["شکستن خط"],
    },
    {
      id: "cue-3",
      startSeconds: 11.7,
      endSeconds: 15,
      // Mixed direction: Latin word plus Western digits inside Persian text.
      text: "تجربهٔ ما با Remotion و ۳۰ فریم در ثانیه",
      highlightPhrases: ["Remotion"],
    },
    {
      id: "cue-4",
      startSeconds: 15.2,
      endSeconds: 18,
      text: "خوانایی و زیبایی هم‌زمان",
      highlightPhrases: ["خوانایی", "زیبایی"],
    },
  ],
};

/** Landscape variant of the same fixture, for checking both formats. */
export const persianDemoFixtureLandscape: PersianVideoProps = {
  ...persianDemoFixture,
  format: "landscape",
};

/**
 * The `defaultProps` for the two render-target compositions.
 *
 * Remotion shallow-merges `--props` over `defaultProps`, so `defaultProps` is not
 * merely a studio convenience: every key a render omits is inherited. That makes an
 * opaque default actively dangerous here. With the demo fixture as the default, a
 * render that passed no `typographicBeats` inherited the demo's two beats, and the
 * typographic plate — opaque by design, since it is an alternative to footage rather
 * than an overlay — covered the footage for the first 18 seconds. The render
 * succeeded, the props validated, and the footage was never visible.
 *
 * So the default states every optional key that can paint, and states it as empty.
 * A key that is absent here is a key a caller can silently inherit.
 */
export const persianEmptyFixture: PersianVideoProps = {
  format: "vertical",
  durationSeconds: 1,
  shots: [],
  cues: [],
  typographicBeats: [],
  watermark: DEFAULT_WATERMARK,
};

/** Landscape counterpart of the empty default. */
export const persianEmptyFixtureLandscape: PersianVideoProps = {
  ...persianEmptyFixture,
  format: "landscape",
};
