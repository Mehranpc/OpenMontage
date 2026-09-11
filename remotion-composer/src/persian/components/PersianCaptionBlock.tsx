import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { ESTEDAD_FAMILY } from "../fonts";
import {
  CAPTION_FONT_PX,
  CAPTION_HORIZONTAL_PADDING_PX,
  CAPTION_LINE_HEIGHT,
  CAPTION_VERTICAL_PADDING_PX,
  captionBandRect,
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

  const rect = captionBandRect(format, design);
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
          padding: `${CAPTION_VERTICAL_PADDING_PX}px ${CAPTION_HORIZONTAL_PADDING_PX}px`,
          borderRadius: 14,
          background: "rgba(25, 25, 25, 0.78)",
          color: "#FFFFFF",
          fontFamily: ESTEDAD_FAMILY,
          fontSize: CAPTION_FONT_PX[format],
          fontWeight: 700,
          lineHeight: CAPTION_LINE_HEIGHT,
          textAlign: "center",
          textShadow: "0 2px 8px rgba(0, 0, 0, 0.55)",
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
