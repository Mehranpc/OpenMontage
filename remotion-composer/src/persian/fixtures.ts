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
 * The moments exercise the cases that break Persian rendering, deliberately:
 *   - ZWNJ words («می‌کند», «شرکت‌کنندگان», «هم‌گروهی») — the measure-vs-paint split.
 *   - A proclitic and an enclitic near a likely break point — the break rules.
 *   - An explicit ezafe («مطالعهٔ», «تجربهٔ») — the no-break-after-ezafe rule.
 *   - Mixed Persian, Latin, and digits in one moment — bidi isolation.
 *   - A lead long enough to need two lines — the fitter and the ladder.
 *   - A one-word hero and a sentence-length hero — the two ends of the ladder.
 *   - An authored build (`revealAfterSeconds`) — additive reveal inside one moment.
 *
 * It also demonstrates three rules that are easy to regress and invisible in a
 * still frame:
 *
 * 1. **Segment order is reading order.** «مطالعهٔ دانشگاه اولوی فنلاند روی» is
 *    written before «۲۲۶۴ نفر» because Persian states the frame before the fact,
 *    and the component paints the array in order with no sorting of its own. Swap
 *    the two entries and the render swaps them too — that is the contract.
 * 2. **The first moment opens the video.** `moment-1` starts at 0.4s, inside
 *    `OPENING_MOMENT_MAX_START_SECONDS`, because short-form feeds autoplay muted:
 *    an opening on silent footage has nothing on screen to hold a thumb.
 * 3. **Pacing.** 20 seconds carry four moments with real gaps between them, not a
 *    continuous band of text.
 */

import type { PersianVideoProps } from "./types";
import { DEFAULT_WATERMARK } from "./types";

export const persianDemoFixture: PersianVideoProps = {
  format: "vertical",
  durationSeconds: 20,
  shots: [],
  captionMode: "sidecar_only",
  captions: [],
  typographicBeats: [
    { id: "beat-1", startSeconds: 0, endSeconds: 10 },
    { id: "beat-2", startSeconds: 10, endSeconds: 20 },
  ],
  watermark: DEFAULT_WATERMARK,
  moments: [
    {
      // Opens the video: on screen by 0.4s, so a muted autoplay still says
      // something. A figure whose lead names what the number counts — the case the
      // slot model could not express, which is why it produced a bare «۲۲۶۴» over
      // a university name with no sentence between them.
      id: "moment-1",
      kind: "figure",
      startSeconds: 0.4,
      endSeconds: 4.4,
      anchorText: "مطالعه",
      segments: [
        { role: "lead", text: "مطالعهٔ دانشگاه اولوی فنلاند روی" },
        { role: "hero", text: "۲۲۶۴ نفر" },
      ],
    },
    {
      // A build: the second fact joins the first rather than replacing it, so the
      // two read as one thought. One moment, two reveals — not two moments, which
      // is why the inter-moment gap floor does not apply between them.
      id: "moment-2",
      kind: "figure",
      startSeconds: 5.4,
      endSeconds: 11.2,
      segments: [
        { role: "lead", text: "میانگین سنی شرکت‌کنندگان:" },
        { role: "hero", text: "۴۶ سال" },
        { role: "lead", text: "با پیگیری", revealAfterSeconds: 2.6 },
        { role: "hero", text: "۱۲ ساله", revealAfterSeconds: 2.6 },
      ],
    },
    {
      // A term whose gloss follows the name, so the phrase needs a `tail` rather
      // than a second `lead`: «SHBG» is the subject and the gloss completes it.
      // Also the bidi case — a Latin acronym as the hero of an RTL phrase.
      id: "moment-3",
      kind: "term",
      startSeconds: 12.2,
      endSeconds: 16.0,
      segments: [
        { role: "hero", text: "SHBG" },
        { role: "tail", text: "پروتئینی که هورمون‌های جنسی را حمل می‌کند" },
        { role: "source", text: "دانشگاه اولو، ۲۰۲۴" },
      ],
    },
    {
      // A statement: the emphasis is a span inside the sentence, not a separate
      // object. Long enough to exercise the breaker, and it contains «به» and «را»
      // where a greedy CSS wrap would strand them at a line end. Mixed direction
      // too: a Latin word and Western digits inside Persian text.
      id: "moment-4",
      kind: "statement",
      startSeconds: 17.0,
      endSeconds: 20,
      segments: [
        { role: "lead", text: "تجربهٔ ما با Remotion و ۳۰ فریم در ثانیه:" },
        { role: "hero", text: "خطِ فارسی را رها نکن" },
      ],
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
  moments: [],
  typographicBeats: [],
  captionMode: "sidecar_only",
  captions: [],
  watermark: DEFAULT_WATERMARK,
};

/** Landscape counterpart of the empty default. */
export const persianEmptyFixtureLandscape: PersianVideoProps = {
  ...persianEmptyFixture,
  format: "landscape",
};
