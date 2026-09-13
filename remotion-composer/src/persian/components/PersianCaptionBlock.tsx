import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { ESTEDAD_FAMILY } from "../fonts";
import {
  captionBandRect,
  captionPaintStyle,
} from "../captionLayout";
import type {
  PersianCaption,
  PersianDesignSnapshot,
  PersianMoment,
} from "../types";
import type { PersianFormat } from "../tokens";

export const PersianCaptionBlock: React.FC<{
  caption: PersianCaption;
  format: PersianFormat;
  moments: readonly PersianMoment[];
  design?: PersianDesignSnapshot;
}> = ({ caption, format, moments, design }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (caption.lines.length < 1 || caption.lines.length > 2) {
    throw new Error(`Caption ${caption.id} must contain one or two lines.`);
  }

  // Caption timing is local to its Sequence. Convert back to absolute timeline time
  // only for the one interaction rule: authored moments own the frame whenever they
  // are active. This makes caption+moment overlap unpaintable even if their raw timing
  // windows overlap.
  const absoluteSeconds = caption.startSeconds + frame / fps;
  const momentOwnsFrame = moments.some(
    (moment) =>
      absoluteSeconds >= moment.startSeconds && absoluteSeconds < moment.endSeconds,
  );
  if (momentOwnsFrame) return null;

  // If a cue begins under an editorial moment and only a sub-second tail remains
  // after that moment exits, suppress the whole burned cue. Painting that residue
  // creates a one-frame/flash caption (for example the end of the opening CTA) even
  // though the moment intentionally owned almost all of its reading window. The
  // sidecar still keeps the approved words; only the stranded burned fragment is
  // hidden.
  const strandedAfterMoment = moments.some(
    (moment) =>
      caption.startSeconds >= moment.startSeconds &&
      caption.startSeconds < moment.endSeconds &&
      caption.endSeconds > moment.endSeconds &&
      caption.endSeconds - moment.endSeconds < 1.0,
  );
  if (strandedAfterMoment) return null;

  const rect = captionBandRect(format, design);
  const style = captionPaintStyle(format, design);
  return (
    <div
      style={{
        position: "absolute",
        left: `${rect.x * 100}%`,
        top: `${rect.y * 100}%`,
        width: `${rect.w * 100}%`,
        height: `${rect.h * 100}%`,
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "center",
        pointerEvents: "none",
        direction: "rtl",
      }}
    >
      <div
        style={{
          maxWidth: "100%",
          padding: `${style.verticalPaddingPx}px ${style.horizontalPaddingPx}px`,
          borderRadius: style.borderRadiusPx,
          background: style.background,
          color: "#FFFFFF",
          fontFamily: ESTEDAD_FAMILY,
          fontSize: style.fontPx,
          fontWeight: style.fontWeight,
          lineHeight: style.lineHeight,
          textAlign: "center",
          textShadow: style.textShadow,
          unicodeBidi: "plaintext",
        }}
      >
        {caption.lines.map((line, index) => (
          <div key={`${caption.id}-line-${index}`}>{line}</div>
        ))}
      </div>
    </div>
  );
};
