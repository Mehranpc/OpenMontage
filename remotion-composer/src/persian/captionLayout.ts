import { FORMAT_DIMENSIONS, SAFE_AREA, type PersianFormat } from "./tokens";
import { ESTEDAD_FAMILY } from "./fonts";
import type { PersianCaption, PersianDesignSnapshot } from "./types";

export const CAPTION_FONT_PX: Record<PersianFormat, number> = {
  vertical: 48,
  landscape: 40,
};
export const CAPTION_LINE_HEIGHT = 1.38;
export const CAPTION_VERTICAL_PADDING_PX = 12;
export const CAPTION_HORIZONTAL_PADDING_PX = 18;
export const CAPTION_EDGE_GAP_FRACTION = 0.015;

export type CaptionSafeArea = {
  top: number;
  bottom: number;
  left: number;
  right: number;
};

export function captionSafeArea(
  format: PersianFormat,
  design?: PersianDesignSnapshot,
): CaptionSafeArea {
  const fallback = SAFE_AREA[format];
  const resolved = (design?.resolved as any)?.formats?.[format]?.safeArea;
  const side = Number(resolved?.side ?? fallback.side);
  return {
    top: Number(resolved?.top ?? fallback.top),
    bottom: Number(resolved?.bottom ?? fallback.bottom),
    left: Number(resolved?.left ?? side),
    right: Number(resolved?.right ?? side),
  };
}

/** Conservative two-line caption envelope, normalized to the frame. */
export function captionBandRect(
  format: PersianFormat,
  design?: PersianDesignSnapshot,
): { x: number; y: number; w: number; h: number } {
  const safe = captionSafeArea(format, design);
  const dims = FORMAT_DIMENSIONS[format];
  const lineBox = CAPTION_FONT_PX[format] * CAPTION_LINE_HEIGHT;
  const heightPx = 2 * lineBox + 2 * CAPTION_VERTICAL_PADDING_PX;
  const h = heightPx / dims.height;
  // Film Type 2.13 physically centres the burned-caption panel in the frame.
  // The vertical safe area is intentionally asymmetric (more room reserved on the
  // right for Reels UI), so centring within the raw safe-area span would leave the
  // panel visibly left-shifted. Use the stricter side inset symmetrically; older
  // pinned profiles keep their exact historical rectangle.
  const physicallyCentered = design?.profile === "film-type" && design.profileVersion === "2.13.0";
  const x = physicallyCentered
    ? Math.max(safe.left, safe.right) + CAPTION_EDGE_GAP_FRACTION
    : safe.left + CAPTION_EDGE_GAP_FRACTION;
  const w = physicallyCentered
    ? Math.max(0, 1 - 2 * x)
    : Math.max(0, 1 - safe.left - safe.right - 2 * CAPTION_EDGE_GAP_FRACTION);
  const y = Math.max(
    safe.top,
    1 - safe.bottom - CAPTION_EDGE_GAP_FRACTION - h,
  );
  return { x, y, w, h };
}

let captionCanvas: CanvasRenderingContext2D | null = null;

function captionLineWidthPx(text: string, format: PersianFormat): number {
  if (!captionCanvas) captionCanvas = document.createElement("canvas").getContext("2d");
  if (!captionCanvas) throw new Error("Persian captions require a browser canvas for text measurement.");
  captionCanvas.font = `700 ${CAPTION_FONT_PX[format]}px "${ESTEDAD_FAMILY}"`;
  captionCanvas.direction = "rtl";
  return captionCanvas.measureText(text).width;
}

/** Browser-side caption proof using the exact font/size the component paints. */
export function assertCaptionsFit(
  format: PersianFormat,
  captions: readonly PersianCaption[],
  durationSeconds: number,
  design?: PersianDesignSnapshot,
): void {
  const dims = FORMAT_DIMENSIONS[format];
  const rect = captionBandRect(format, design);
  const availableWidthPx = rect.w * dims.width - 2 * CAPTION_HORIZONTAL_PADDING_PX;
  let previousEnd = -Infinity;
  for (const caption of captions) {
    if (caption.lines.length < 1 || caption.lines.length > 2) {
      throw new Error(`Caption ${caption.id} must contain one or two lines.`);
    }
    if (caption.lines.join(" ") !== caption.text) {
      throw new Error(`Caption ${caption.id} line breaks changed approved text.`);
    }
    if (![caption.startSeconds, caption.endSeconds].every(Number.isFinite) ||
        caption.startSeconds < 0 || caption.endSeconds <= caption.startSeconds ||
        caption.endSeconds > durationSeconds + 1e-6) {
      throw new Error(`Caption ${caption.id} timing is outside the video.`);
    }
    if (caption.startSeconds < previousEnd - 1e-6) {
      throw new Error(`Caption ${caption.id} overlaps the previous burned caption.`);
    }
    for (const line of caption.lines) {
      const width = captionLineWidthPx(line, format);
      if (width > availableWidthPx + 0.5) {
        throw new Error(
          `Caption ${caption.id} line is ${width.toFixed(1)}px wide but only ` +
          `${availableWidthPx.toFixed(1)}px is safe. Tighten cue grouping; do not shrink type.`,
        );
      }
    }
    previousEnd = caption.endSeconds;
  }
}
