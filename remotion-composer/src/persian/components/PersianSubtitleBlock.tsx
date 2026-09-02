/**
 * Persian glass subtitle block.
 *
 * Renders one cue inside a frosted panel, with RTL-correct word order, karaoke
 * emphasis when word timings exist, and staggered arrivals when they do not.
 *
 * ## Why the lines are laid out manually
 *
 * Each line is its own flex row and the words are individual spans placed in
 * source order with `direction: rtl`. Nothing is left to CSS wrapping — the break
 * points come from `layout.ts`, which measured them against real Estedad metrics
 * under Persian grammatical constraints. Letting the browser re-wrap would
 * discard that work and reintroduce the exact breaks the layout pass exists to
 * prevent.
 *
 * ## Why per-word spans instead of one text node
 *
 * Karaoke needs to transform and glow one word at a time. That requires a
 * per-word element. The cost is that the browser no longer shapes across word
 * boundaries — which is fine here, because Persian words are separated by real
 * spaces and Arabic-script joining does not cross a space. (It *would* be wrong
 * to split inside a word: that breaks the joining forms and produces isolated
 * letterforms, the classic broken-Persian look.)
 */

import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";

import { estedadCanvasFont, ESTEDAD_FAMILY } from "../fonts";
import { fitBlock, type LayoutResult } from "../layout";
import {
  glow,
  holdLife,
  materialEnter,
  materialExit,
  staggerDelay,
} from "../motion";
import { compareKey, ZWNJ } from "../text";
import {
  GLASS,
  KARAOKE,
  PERSIAN_PALETTE,
  SUBTITLE_TEXT_SHADOW,
  TYPOGRAPHY,
  computeLineBudgetPx,
  type PersianFormat,
} from "../tokens";
import type { PersianCue } from "../types";

export interface PersianSubtitleBlockProps {
  readonly cue: PersianCue;
  readonly format: PersianFormat;
  /** Frame at which this cue's sequence began, for local timing. */
  readonly cueStartFrame: number;
  readonly cueDurationFrames: number;
}

/** Emphasis state of one word at one frame. */
interface WordEmphasis {
  /** 0 = no emphasis, 1 = fully emphasised. */
  readonly amount: number;
  readonly isHighlighted: boolean;
}

/**
 * How emphasised a word is at this frame.
 *
 * Ramps in and out over `KARAOKE.edgeFrames` rather than switching, because a
 * hard switch on a 1.08 scale reads as a twitch. The ramp is linear: the window
 * is only three frames, so easing inside it is imperceptible and only costs
 * clarity here.
 */
function wordEmphasis(
  frame: number,
  fps: number,
  word: { startSeconds: number; endSeconds: number } | undefined,
  isHighlighted: boolean,
): WordEmphasis {
  if (!word) return { amount: 0, isHighlighted };

  const startFrame = word.startSeconds * fps;
  const endFrame = word.endSeconds * fps;
  const edge = KARAOKE.edgeFrames;

  if (frame < startFrame - edge || frame > endFrame + edge) {
    return { amount: 0, isHighlighted };
  }

  if (frame < startFrame) {
    return { amount: (frame - (startFrame - edge)) / edge, isHighlighted };
  }
  if (frame > endFrame) {
    return { amount: 1 - (frame - endFrame) / edge, isHighlighted };
  }
  return { amount: 1, isHighlighted };
}

/**
 * Match cue words against the highlight phrases.
 *
 * Compares on `compareKey`, so a phrase written with different ک/ی encodings or
 * with trailing punctuation still matches. Multi-word phrases mark every word
 * they cover, so the whole phrase emphasises together.
 */
function resolveHighlights(
  words: readonly string[],
  phrases: readonly string[] | undefined,
): boolean[] {
  const flags = new Array(words.length).fill(false);
  if (!phrases || phrases.length === 0) return flags;

  const keys = words.map(compareKey);
  for (const phrase of phrases) {
    const phraseKeys = phrase.split(/\s+/).map(compareKey).filter(Boolean);
    if (phraseKeys.length === 0) continue;

    for (let i = 0; i + phraseKeys.length <= keys.length; i += 1) {
      let matched = true;
      for (let j = 0; j < phraseKeys.length; j += 1) {
        if (keys[i + j] !== phraseKeys[j]) {
          matched = false;
          break;
        }
      }
      if (matched) {
        for (let j = 0; j < phraseKeys.length; j += 1) flags[i + j] = true;
      }
    }
  }
  return flags;
}

/**
 * Index each laid-out word back to its position in the flat cue word list, so
 * word timings (which are flat) can be looked up per line without re-splitting.
 */
function flattenIndices(lines: string[][]): number[][] {
  let cursor = 0;
  return lines.map((line) =>
    line.map(() => {
      const index = cursor;
      cursor += 1;
      return index;
    }),
  );
}

export const PersianSubtitleBlock: React.FC<PersianSubtitleBlockProps> = ({
  cue,
  format,
  cueStartFrame,
  cueDurationFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const typography = TYPOGRAPHY[format];

  // Layout is a pure function of (text, budget, size), so it is memoized on
  // exactly those. Recomputing per frame would re-measure on canvas 30 times a
  // second for a result that cannot change.
  const layout: LayoutResult = React.useMemo(
    () =>
      fitBlock(cue.text, {
        maxWidthPx: computeLineBudgetPx(format),
        maxLines: typography.maxLines,
        maxLinesEscalated: typography.maxLinesEscalated,
        fontSizePx: typography.subtitleFontSizePx,
        weight: 500,
      }),
    [
      cue.text,
      format,
      typography.maxLines,
      typography.maxLinesEscalated,
      typography.subtitleFontSizePx,
    ],
  );

  const flatWords = React.useMemo(
    () => layout.lines.flat(),
    [layout.lines],
  );
  const highlightFlags = React.useMemo(
    () => resolveHighlights(flatWords, cue.highlightPhrases),
    [flatWords, cue.highlightPhrases],
  );
  const lineIndices = React.useMemo(
    () => flattenIndices(layout.lines),
    [layout.lines],
  );

  const fontSize = typography.subtitleFontSizePx * layout.fontScale;

  // The panel enters and exits as one unit; the words stagger inside it. Two
  // levels of animation, so the panel does not appear to pop per word.
  const panelEnter = materialEnter(frame, cueStartFrame, fps, "standard");
  const panelExit = materialExit(
    frame,
    cueStartFrame + cueDurationFrames,
    fps,
    "standard",
  );
  const panelOpacity = Math.min(panelEnter.opacity, panelExit.opacity);

  if (layout.lines.length === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: typography.subtitleBottomPx,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        // The subtitle layer never intercepts input; it is a render-only overlay.
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          // `border-box` is required, not cosmetic: the horizontal padding is
          // large, and with `content-box` the panel would exceed maxWidth and
          // no longer match the width the layout pass measured against.
          boxSizing: "border-box",
          maxWidth: `${GLASS.maxWidthFraction * 100}%`,
          padding: `${typography.glassPaddingPx[0]}px ${typography.glassPaddingPx[1]}px`,
          backgroundColor: GLASS.backgroundColor,
          backdropFilter: `blur(${GLASS.blurPx}px)`,
          WebkitBackdropFilter: `blur(${GLASS.blurPx}px)`,
          borderRadius: GLASS.borderRadiusPx,
          boxShadow: GLASS.boxShadow,
          opacity: panelOpacity,
          transform: panelEnter.transform !== "none" ? panelEnter.transform : panelExit.transform,
          direction: "rtl",
        }}
      >
        {layout.lines.map((line, lineIndex) => (
          <div
            key={lineIndex}
            style={{
              display: "flex",
              flexDirection: "row",
              // RTL on the flex row, so source order is reading order and the
              // first word sits at the right edge. Reversing the array instead
              // would break the bidi algorithm for any embedded Latin or digits.
              direction: "rtl",
              justifyContent: "center",
              alignItems: "baseline",
              gap: typography.wordGapPx,
              lineHeight: typography.subtitleLineHeight,
              // No wrapping: breaks are already decided. `nowrap` makes a layout
              // bug visible as overflow rather than hiding it as a silent re-wrap.
              flexWrap: "nowrap",
              whiteSpace: "nowrap",
            }}
          >
            {line.map((word, wordIndexInLine) => {
              const flatIndex = lineIndices[lineIndex][wordIndexInLine];
              const timing = cue.words?.[flatIndex];
              const { amount, isHighlighted } = wordEmphasis(
                frame,
                fps,
                timing,
                highlightFlags[flatIndex],
              );

              // Without word timings, words arrive staggered; with them, they
              // arrive together and the karaoke cursor carries the motion.
              const wordStart = cue.words
                ? cueStartFrame
                : cueStartFrame + staggerDelay(flatIndex);
              const enter = materialEnter(frame, wordStart, fps, "standard");
              const life = holdLife(frame, flatIndex * 7);

              const emphasised = amount > 0;
              const color = isHighlighted
                ? PERSIAN_PALETTE.highlight
                : PERSIAN_PALETTE.text;
              const scale = 1 + (KARAOKE.activeScale - 1) * amount;

              const shadows = [SUBTITLE_TEXT_SHADOW];
              if (emphasised) {
                shadows.push(
                  glow(
                    isHighlighted
                      ? PERSIAN_PALETTE.highlight
                      : PERSIAN_PALETTE.text,
                    KARAOKE.glowRadiusPx,
                    amount * life.glowAlpha,
                  ),
                );
              }

              return (
                <span
                  key={`${flatIndex}-${word}`}
                  style={{
                    fontFamily: ESTEDAD_FAMILY,
                    fontWeight: isHighlighted ? 700 : 500,
                    fontSize,
                    color,
                    textShadow: shadows.join(", "),
                    opacity: enter.opacity,
                    // Emphasis is scale + glow only. Never font-weight on the
                    // karaoke axis: changing weight changes every advance width,
                    // so the line re-flows under the cursor and visibly jitters.
                    transform:
                      enter.transform === "none" && !emphasised
                        ? "none"
                        : `${enter.transform === "none" ? "" : enter.transform} scale(${scale.toFixed(4)})`.trim(),
                    filter: enter.filter,
                    // `embed` isolates each word's bidi run, so a Latin token or
                    // a number inside a Persian line does not reorder its
                    // neighbours.
                    unicodeBidi: "embed",
                    direction: "rtl",
                    display: "inline-block",
                  }}
                >
                  {word}
                </span>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
};

/** Exported for tests: the canvas font string the block measures with. */
export const subtitleCanvasFont = (format: PersianFormat): string =>
  estedadCanvasFont(TYPOGRAPHY[format].subtitleFontSizePx, 500);

/** Exported for tests: ZWNJ must survive into the painted string. */
export const PAINTED_ZWNJ = ZWNJ;
