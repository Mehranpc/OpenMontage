import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { ESTEDAD_FAMILY } from "../fonts";
import { FORMAT_DIMENSIONS, SAFE_AREA, computeMomentCentreFraction, type PersianFormat } from "../tokens";
import { fitMoment, inkTrimMargins, resolveMomentGeometry } from "../layout";
import { compareKey } from "../text";
import { assertMomentIsWellFormed, type PersianDesignSnapshot, type PersianMoment } from "../types";

export const PersianV2MomentBlock: React.FC<{ moment: PersianMoment; format: PersianFormat; durationFrames: number; design: PersianDesignSnapshot }> = ({ moment, format, durationFrames, design }) => {
  assertMomentIsWellFormed(moment);
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const resolved = (design.resolved ?? {}) as any;
  const typography = resolved.typography ?? {};
  const safe = resolved.formats?.[format]?.safeArea ?? SAFE_AREA[format];
  const fitted = fitMoment(moment.segments, format, moment.kind);
  const geometry = moment.layoutGeometry ?? resolveMomentGeometry(fitted, format, moment.presentation?.placement ?? "auto", safe);
  const treatment = moment.presentation?.treatment ?? "editorial";
  const placement = moment.presentation?.placement ?? (treatment === "inline-statement" ? "lower-right" : "center");
  const motion = moment.presentation?.motion ?? (treatment === "inline-statement" ? "cut-in" : "soft-reveal");
  const enter = motion === "cut-in" ? 5 : 14;
  const leave = motion === "cut-in" ? 5 : 14;
  const progress = interpolate(frame, [0, enter, Math.max(enter, durationFrames - leave), durationFrames], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const motionY = motion === "cut-in" ? (1 - progress) * 22 : (1 - progress) * 10;
  // Resolve a stable contrast mode once per moment; never flip colors per frame.
  const contrastMode = (moment as any).presentation?.contrastMode === "light" ? "light" : "dark";
  const color = contrastMode === "light" ? (typography.contrastModes?.light?.ink ?? typography.darkInk ?? "#191919") : (typography.contrastModes?.dark?.ink ?? typography.ink ?? "#F0EDE6");
  const accent = typography.accent ?? "#1789FC";
  const scale = Number(typography.scale ?? 1);
  const accentsByRole = new Map(
    moment.segments.map((segment) => [segment.role, new Set((segment.accentWords ?? []).map(compareKey))]),
  );
  // V2 role settings are explicit: only a declared hero is prominent; body ink is
  // neutral and inline emphasis colors only the authored matching words.
  const isHook = moment.kind === "hook";
  const dims = FORMAT_DIMENSIONS[format];
  const width = geometry.w * dims.width;
  const positions: Record<string, React.CSSProperties> = {
    "upper-left": { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    "upper-right": { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    "mid-left": { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    "mid-right": { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    "lower-left": { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    "lower-right": { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    center: { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
    auto: { left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`, transform: `translateY(${motionY}px)` },
  };
  const style = positions[placement] ?? positions.auto;
  return <AbsoluteFill style={{ pointerEvents: "none" }}><div data-persian-v2-moment={moment.id} data-persian-treatment={treatment} data-persian-placement={placement} data-persian-contrast={contrastMode} data-persian-font-family={ESTEDAD_FAMILY} style={{ position: "absolute", width, direction: "rtl", textAlign: "right", opacity: progress, ...style }}>
    {fitted.segments.map((segment, index) => <div data-persian-v2-segment={`${moment.id}:${segment.role}:${index}`} key={`${segment.role}-${index}`} style={{ fontFamily: ESTEDAD_FAMILY, fontWeight: segment.weight, fontSize: segment.fontSizePx * scale, lineHeight: `${segment.fontSizePx * scale + segment.lineGapPx}px`, color: color, textShadow: "0 2px 10px rgba(0,0,0,.45)", marginBottom: index < fitted.segments.length - 1 ? fitted.stackGapPx : 0, whiteSpace: "nowrap" }}>
      {segment.lines.map((line, lineIndex) => <div key={lineIndex} style={{ display: "flex", justifyContent: "flex-start", gap: `${Math.round(segment.fontSizePx * 0.22)}px`, flexWrap: "nowrap", ...inkTrimMargins(segment.inkPerLine[lineIndex], segment.fontSizePx, 1.075, 0.59) }}>{line.map((word, wordIndex) => { const isAccent = (accentsByRole.get(segment.role)?.has(compareKey(word)) ?? false) && moment.presentation?.emphasis === "inline"; return <span key={wordIndex} style={{ color: isAccent ? accent : color }}>{word}</span>; })}</div>)}
    </div>)}
  </div></AbsoluteFill>;
};
