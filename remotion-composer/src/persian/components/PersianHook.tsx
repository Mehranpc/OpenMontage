/**
 * Opening hook line.
 *
 * The first two to four seconds decide whether anyone watches the rest, so the
 * hook gets its own treatment: heavier weight, larger size, upper third of the
 * frame, and no glass panel. It sits over the first shot directly — the panel
 * would frame it as a subtitle, and the hook is not a subtitle, it is a title.
 *
 * Emphasis inside the hook is marked with `*asterisks*` in the source text. That
 * is a deliberate choice over passing a separate phrase list: the hook is a single
 * authored line, and keeping the emphasis inline means the writer can see it in
 * the text they are writing rather than maintaining a parallel array that can
 * drift out of sync with the words.
 */

import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";

import { ESTEDAD_FAMILY } from "../fonts";
import { materialEnter, staggerDelay, STAGGER } from "../motion";
import { splitWords } from "../text";
import {
  PERSIAN_PALETTE,
  SUBTITLE_TEXT_SHADOW,
  TYPOGRAPHY,
  type PersianFormat,
} from "../tokens";

export interface PersianHookProps {
  readonly text: string;
  readonly format: PersianFormat;
  readonly durationFrames: number;
}

/** Seconds of fade at the end of the hook, so it hands off rather than cutting. */
const FADE_OUT_SECONDS = 0.5;

interface HookToken {
  readonly word: string;
  readonly emphasised: boolean;
}

/**
 * Parse `*emphasis*` markers.
 *
 * Markers are stripped from the rendered word, so the asterisks never appear on
 * screen. A word is emphasised if it carried a marker on either side, which means
 * a multi-word emphasis can be written `*مثل این*` and both words light up.
 */
function parseHook(text: string): HookToken[] {
  let inEmphasis = false;
  return splitWords(text)
    .filter((word) => word !== "\n")
    .map((raw) => {
      const opens = raw.startsWith("*");
      const closes = raw.endsWith("*");
      const word = raw.replace(/^\*+|\*+$/g, "");

      // A single-token `*word*` opens and closes at once; a multi-token span
      // opens on the first and closes on the last.
      const emphasised = inEmphasis || opens;
      if (opens && !closes) inEmphasis = true;
      if (closes) inEmphasis = false;

      return { word, emphasised };
    });
}

export const PersianHook: React.FC<PersianHookProps> = ({
  text,
  format,
  durationFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const typography = TYPOGRAPHY[format];

  const tokens = React.useMemo(() => parseHook(text), [text]);

  const fadeFrames = Math.round(FADE_OUT_SECONDS * fps);
  const fadeStart = Math.max(0, durationFrames - fadeFrames);
  // Guard the range: on a hook shorter than its own fade, `fadeStart` would equal
  // `durationFrames` and `interpolate` throws on a non-increasing range.
  const opacity =
    durationFrames > fadeFrames
      ? interpolate(frame, [fadeStart, durationFrames], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;

  return (
    <div
      style={{
        position: "absolute",
        // Upper third: above the subtitle band, below the top safe area, and in
        // the region a viewer's eye lands on first.
        top: format === "vertical" ? "18%" : "14%",
        left: 0,
        right: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 10,
        opacity,
        pointerEvents: "none",
        direction: "rtl",
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          flexWrap: "wrap",
          justifyContent: "center",
          direction: "rtl",
          gap: typography.wordGapPx,
          maxWidth: "82%",
        }}
      >
        {tokens.map((token, index) => {
          // `hero` weight: the hook arrives more slowly and with more travel than
          // body text, which is what makes it read as a title rather than a cue.
          const enter = materialEnter(
            frame,
            staggerDelay(index, STAGGER.word),
            fps,
            "hero",
          );
          return (
            <span
              key={`${index}-${token.word}`}
              style={{
                fontFamily: ESTEDAD_FAMILY,
                // 900 for emphasis, 700 for the rest. Both are real vendored
                // weights, so nothing is synthesized.
                fontWeight: token.emphasised ? 900 : 700,
                fontSize: typography.hookFontSizePx,
                color: token.emphasised
                  ? PERSIAN_PALETTE.hookEmphasis
                  : PERSIAN_PALETTE.text,
                textShadow: SUBTITLE_TEXT_SHADOW,
                opacity: enter.opacity,
                transform: enter.transform,
                filter: enter.filter,
                lineHeight: 1.25,
                direction: "rtl",
                unicodeBidi: "embed",
                display: "inline-block",
              }}
            >
              {token.word}
            </span>
          );
        })}
      </div>
    </div>
  );
};
