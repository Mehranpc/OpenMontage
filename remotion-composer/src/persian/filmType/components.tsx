import {diffuseRadii,diffuseStops} from "./diffuse27";
/** Film Type paint. All movement is frame-driven; no CSS animation/timers. */
import React, { useId, useMemo } from "react";
import { AbsoluteFill, Easing, useCurrentFrame, useVideoConfig } from "remotion";
import { compareKey } from "../text";
import { FORMAT_DIMENSIONS, type PersianFormat } from "../tokens";
import type { PersianMoment, PersianDesignSnapshot, PersianVideoProps } from "../types";
import { filmProfile, filmRowDelay, isFilmTypePolish, type FilmRow, type FilmMomentLayout, type FilmLockup, type Rect } from "./layout";

import { gentleLife, featherLayers, compactPath } from "./motion24";

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const ease = Easing.bezier(.22, 1, .36, 1);
export function filmLife(seconds: number, span: number, delay: number, enter: number, exit: number) {
  const available = Math.max(.001, span - delay);
  const inTime = Math.min(enter, available / 2), outTime = Math.min(exit, available / 2);
  const arrive = ease(clamp01((seconds - delay) / inTime));
  const leave = clamp01((span - seconds) / outTime);
  return { arrive, leave, opacity: arrive * leave };
}

/** An ellipse with a real flat-opacity core enclosing ALL four text corners.
 * Feathering happens outside that core, never under small source/context text.
 * It is local, not a frame-wide grade or a rectangular text card. */
export const FilmContrastField: React.FC<{
  rect: Rect; format: PersianFormat; color: string; alpha: number;
  plateau: number; paddingPx: number; opacity: number; kind: "text" | "brand";
}> = ({rect,format,color,alpha,plateau,paddingPx,opacity,kind}) => {
  const id = useId();
  const d = FORMAT_DIMENSIONS[format];
  const cx = (rect.x + rect.w / 2) * d.width, cy = (rect.y + rect.h / 2) * d.height;
  const rx = (rect.w * d.width / 2 + paddingPx) * Math.SQRT2 / plateau;
  const ry = (rect.h * d.height / 2 + paddingPx) * Math.SQRT2 / plateau;
  return <svg data-film-type-field={kind} width={d.width} height={d.height} viewBox={`0 0 ${d.width} ${d.height}`} style={{position:"absolute",inset:0,pointerEvents:"none",zIndex:1,opacity}} aria-hidden="true">
    <defs><radialGradient id={id} cx="50%" cy="50%" r="50%">
      <stop offset="0%" stopColor={color} stopOpacity={alpha}/>
      <stop offset={`${plateau * 100}%`} stopColor={color} stopOpacity={alpha}/>
      <stop offset="100%" stopColor={color} stopOpacity={0}/>
    </radialGradient></defs>
    <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill={`url(#${id})`}/>
  </svg>;
};

/** No stroke, card border, backdrop blur, or frame-wide grade. In 2.5.0 the
 * field blends as multiply, so footage hue survives and the darkening reads
 * as a soft shadow dissolving outward instead of a flat grey plate. */
const CompactFilmField: React.FC<{rect:Rect;format:PersianFormat;design:PersianDesignSnapshot;color:string;alpha:number;opacity:number;travel:number;featherPx?:number}>=({rect,format,design,color,alpha,opacity,travel,featherPx})=>{
 const id=useId(),p=filmProfile(design),cfg=p.contrast.compactField;
 if(!cfg)throw new Error("Film Type compact field configuration is missing");
 const dark=color===p.contrast.darkField,blend=dark&&cfg.blend==="multiply"?"multiply":undefined,curve=cfg.featherCurve??1;
 const d=FORMAT_DIMENSIONS[format],w=rect.w*d.width,h=rect.h*d.height,cx=(rect.x+rect.w/2)*d.width,cy=(rect.y+rect.h/2)*d.height;
 const layers=useMemo(()=>featherLayers(featherPx ?? cfg.featherPx,cfg.steps,curve).map(layer=>({...layer,path:compactPath(w,h,cfg.paddingPx,layer.expand,cfg.exponent)})),[w,h,cfg.paddingPx,cfg.featherPx,cfg.steps,cfg.exponent,curve,featherPx]);
 return <svg data-film-type-field="text" data-film-field-shape="compact" width={d.width} height={d.height} viewBox={`0 0 ${d.width} ${d.height}`} style={{position:"absolute",inset:0,pointerEvents:"none",zIndex:1,opacity,mixBlendMode:blend}} aria-hidden="true">
  <defs><mask id={id} maskUnits="userSpaceOnUse" x={0} y={0} width={d.width} height={d.height} style={{maskType:"alpha"}}>
   <g transform={`translate(${cx} ${cy+travel})`}>{layers.map((layer,i)=><path key={i} d={layer.path} fill="white" fillOpacity={layer.alpha}/>)}</g>
  </mask></defs>
  <rect width={d.width} height={d.height} fill={color} fillOpacity={alpha} mask={`url(#${id})`}/>
 </svg>;
};

/** 2.9 bounds the field by the frame: the painted shadow is never wider or
 * taller than the video, so it stays a local soft shadow around the ink that
 * fades gently to nothing instead of a frame-sized pale wash. */
const DiffuseField: React.FC<{layout:FilmMomentLayout;format:PersianFormat;design:PersianDesignSnapshot;opacity:number;travel:number}>=({layout,format,design,opacity,travel})=>{
 const id=useId(),p=filmProfile(design),d=FORMAT_DIMENSIONS[format];
 const {rx,ry}=diffuseRadii(layout.widthPx,layout.heightPx,p.contrast.diffuseField!,p.profileVersion === "2.9.0"?{width:d.width,height:d.height}:undefined);
 const cx=(layout.rect.x+layout.rect.w/2)*d.width,cy=(layout.rect.y+layout.rect.h/2)*d.height+travel;
 const dark=layout.contrastMode==="dark",peak=layout.fieldPeakAlpha??p.contrast.strengths[layout.strength];
 return <svg width={d.width} height={d.height} style={{position:"absolute",inset:0,opacity,zIndex:1,mixBlendMode:dark?"multiply":undefined,pointerEvents:"none"}} data-film-field-shape="diffuse">
 <defs><radialGradient id={id}>{diffuseStops.map(s=><stop key={s.offset} offset={s.offset} stopColor={dark?p.contrast.darkField:p.contrast.lightField} stopOpacity={s.alpha*peak}/>)}</radialGradient></defs>
 <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill={`url(#${id})`}/></svg>;
};

const Run: React.FC<{row: FilmRow; x: number; color: string; accent: string; emphasis: boolean; align?: "left" | "right" | "center"}> = ({row,x,color,accent,emphasis,align="right"}) => {
  const accents = new Set(row.accentWords.map(compareKey));
  return <text data-film-type-ink={row.role} data-film-type-segment={row.segmentIndex}
    data-film-type-content={row.text} x={x} y={row.baselinePx}
    direction={row.direction} textAnchor={align === "center" ? "middle" : align === "right" ? (row.direction === "rtl" ? "start" : "end") : (row.direction === "rtl" ? "end" : "start")}
    style={{fontFamily:row.family,fontSize:row.fontSizePx,fontWeight:row.weight,letterSpacing:0,
      fontKerning:"normal",fontSynthesis:"none",unicodeBidi:"isolate",fill:color}}>
    {emphasis && accents.size ? row.text.split(/(\s+)/u).map((part,i) =>
      <tspan key={i} style={accents.has(compareKey(part)) ? {textDecorationLine:"underline",textDecorationColor:accent,textDecorationThickness:"2px",textUnderlineOffset:"5px"} : undefined}>{part}</tspan>
    ) : row.text}
  </text>;
};

export const PersianFilmTypeMoment: React.FC<{
  moment: PersianMoment; layout: FilmMomentLayout; format: PersianFormat;
  durationFrames: number; design: PersianDesignSnapshot;
}> = ({moment,layout,format,durationFrames,design}) => {
  const frame = useCurrentFrame(), {fps} = useVideoConfig();
  const p = filmProfile(design), dims = FORMAT_DIMENSIONS[format];
  const polished = isFilmTypePolish(design);
  if (!layout || layout.id !== moment.id) throw new Error(`Missing measured Film Type layout for ${moment.id}; run persian_compose.`);
  const span = durationFrames / fps, seconds = frame / fps;
  const firstReveal = Math.min(...layout.rows.map(row => row.revealAfterSeconds));
  const modern=p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0"))),lifeAt=modern?gentleLife:filmLife;
  const fieldEnter=modern?(moment.presentation?.motion === "cut-in"?p.motion.cutInSeconds:p.motion.enterSeconds):p.motion.scrimEnterSeconds;
  const fieldLife = lifeAt(seconds,span,firstReveal,fieldEnter,p.motion.exitSeconds);
  const dark = layout.contrastMode === "dark";
  const color = dark ? p.typography.ink : p.typography.darkInk;
  const cut = moment.presentation?.motion === "cut-in";
  const align = layout.placement === "center" ? "center" : polished ? "right" : layout.placement.endsWith("left") ? "left" : "right";
  const anchor = align === "center" ? layout.widthPx/2 : align === "left" ? p.layout.inkPaddingPx : layout.widthPx-p.layout.inkPaddingPx;
  return <AbsoluteFill data-film-type-moment={moment.id} data-film-type-placement={layout.placement} style={{pointerEvents:"none"}}>
    {(p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0") ? <DiffuseField layout={layout} format={format} design={design} opacity={fieldLife.opacity} travel={p.motion.travelPx*(1-fieldLife.arrive)}/> : modern ? <CompactFilmField featherPx={layout.fieldFeatherPx} rect={layout.rect} format={format} design={design} color={dark?p.contrast.darkField:p.contrast.lightField}
      alpha={p.contrast.strengths[layout.strength]} opacity={fieldLife.opacity} travel={p.motion.travelPx*(1-fieldLife.arrive)}/> : <FilmContrastField rect={layout.rect} format={format} color={dark?p.contrast.darkField:p.contrast.lightField}
      alpha={p.contrast.strengths[layout.strength]} plateau={p.contrast.plateauStop}
      paddingPx={p.contrast.plateauPaddingPx + p.motion.travelPx} opacity={fieldLife.opacity} kind="text"/>}
    <svg data-film-type-text={moment.id} width={layout.widthPx} height={layout.heightPx}
      viewBox={`0 0 ${layout.widthPx} ${layout.heightPx}`}
      style={{position:"absolute",left:layout.rect.x*dims.width,top:layout.rect.y*dims.height,overflow:"visible",zIndex:2}}>
      {layout.rows.map((row,index) => {
        // A quantity and its unit share the same authored segment and entrance.
        // Later authored reveal times are never pulled forward or silently lost.
        const delay = filmRowDelay(row,p);
        const life = lifeAt(seconds,span,delay,cut?p.motion.cutInSeconds:p.motion.enterSeconds,p.motion.exitSeconds);
        const y = cut && !modern ? 0 : p.motion.travelPx * (1-life.arrive);
        return <g key={index} data-film-type-row={index} opacity={life.opacity} transform={`translate(0 ${y})`}>
          <Run row={row} x={anchor} align={align} color={color} accent={p.typography.accent} emphasis={moment.presentation?.emphasis === "inline"}/>
        </g>;
      })}
    </svg>
  </AbsoluteFill>;
};

export const PersianFilmTypeWatermark: React.FC<{
  format: PersianFormat; design: PersianDesignSnapshot; lockup: FilmLockup | null;
  plan: PersianVideoProps["watermarkPlan"];
}> = ({format,design,lockup,plan}) => {
  const frame = useCurrentFrame(), {fps} = useVideoConfig();
  const p=filmProfile(design),dims=FORMAT_DIMENSIONS[format],seconds=frame/fps;
  const polished = isFilmTypePolish(design);
  if(!lockup) return null;
  if(!plan) throw new Error("Missing measured Film Type watermark plan; run persian_compose.");
  // Never fall through to the last slot outside its interval; never paint two
  // lockups during relocation. Exit to zero, then enter the next safe slot.
  const entry=plan.find(slot=>seconds>=slot.startSeconds&&seconds<slot.endSeconds);
  if(!entry) return null;
  const opacity=p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0"))) ? gentleLife(seconds-entry.startSeconds,entry.endSeconds-entry.startSeconds,0,p.watermark.transitionSeconds,p.watermark.transitionSeconds).opacity
    : Math.min(1,(seconds-entry.startSeconds)/p.watermark.transitionSeconds,(entry.endSeconds-seconds)/p.watermark.transitionSeconds);
  const align = entry.zone.endsWith("left") ? "left" : "right";
  const anchor = align === "left" ? p.watermark.paddingPx : lockup.widthPx-p.watermark.paddingPx;
  return <AbsoluteFill data-film-type-brand={entry.zone} style={{pointerEvents:"none"}}>
    {!polished && <FilmContrastField rect={entry.rect} format={format} color={p.contrast.darkField} alpha={p.watermark.fieldAlpha}
      plateau={p.contrast.plateauStop} paddingPx={p.watermark.fieldPaddingPx} opacity={opacity} kind="brand"/>}
    <svg data-film-type-watermark="lockup" width={lockup.widthPx} height={lockup.heightPx}
      viewBox={`0 0 ${lockup.widthPx} ${lockup.heightPx}`}
      style={{position:"absolute",left:entry.rect.x*dims.width,top:entry.rect.y*dims.height,overflow:"visible",opacity,zIndex:3}}>
      {lockup.rows.map((row,index)=><Run key={index} row={row} x={anchor} align={align} color={p.typography.ink} accent={p.typography.accent} emphasis={false}/>)}
    </svg>
  </AbsoluteFill>;
};
