import {diffuseRadii,diffuseStops} from "./diffuse27";
/** Film Type paint. All movement is frame-driven; no CSS animation/timers. */
import React, { useEffect, useId, useMemo, useState } from "react";
import { AbsoluteFill, Easing, useCurrentFrame, useVideoConfig } from "remotion";
import { compareKey } from "../text";
import { ensureKahrobaReady, isKahrobaLoaded } from "../fonts";
import { FORMAT_DIMENSIONS, type PersianFormat } from "../tokens";
import type { PersianMoment, PersianDesignSnapshot, PersianVideoProps } from "../types";
import { backdropMultiplier } from "./backdrop";
import { filmProfile, filmRowDelay, isFilmTypePolish, type FilmRow, type FilmMomentLayout, type FilmLockup, type FilmProfile, type FilmPosterDecor, type Rect } from "./layout";

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

/** 2.10 separates letter edges at the glyph: a close shadow for the edge and a
 * wide halo for busy footage. No stroke, no card, no backdrop blur, no grade. */
function shadowFilter(s: {color:string;nearOffsetPx:number;nearBlurPx:number;nearAlpha:number;haloBlurPx:number;haloAlpha:number}): string {
  const match = /^#([0-9a-fA-F]{6})$/.exec(s.color);
  if (!match) throw new Error("Film Type glyph shadow color must be a six-digit hex value.");
  const channel = (at: number) => parseInt(match[1].slice(at, at + 2), 16);
  const rgba = (alpha: number) => `rgba(${channel(0)},${channel(2)},${channel(4)},${alpha})`;
  return `drop-shadow(0 ${s.nearOffsetPx}px ${s.nearBlurPx}px ${rgba(s.nearAlpha)}) drop-shadow(0 0 ${s.haloBlurPx}px ${rgba(s.haloAlpha)})`;
}
export function glyphShadowFilter(p: FilmProfile, busyBackground = false): string | undefined {
  if (p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0" && p.profileVersion !== "2.15.0" && p.profileVersion !== "2.16.0") return undefined;
  const s = p.contrast.glyphShadow;
  if (!s) throw new Error("Film Type 2.10 requires explicit glyph shadow tokens.");
  if (!(busyBackground && p.profileVersion === "2.16.0")) return shadowFilter(s);
  return shadowFilter({
    ...s,
    nearOffsetPx: Math.max(s.nearOffsetPx, 3),
    nearBlurPx: Math.round(s.nearBlurPx * 1.35),
    nearAlpha: Math.min(.82, s.nearAlpha * 1.45),
    haloBlurPx: Math.round(s.haloBlurPx * 1.4),
    haloAlpha: Math.min(.58, s.haloAlpha * 1.7),
  });
}

/** 2.11 gives the brand its own shadow tokens. The 30/24px lockup has thinner
 * strokes than hero type, so it needs a denser shadow for the same contrast.
 * Same two layers as text; the field behind the brand stays unpainted. */
export function watermarkGlyphShadowFilter(p: FilmProfile): string | undefined {
  if (p.profileVersion !== "2.11.0" && p.profileVersion !== "2.15.0" && p.profileVersion !== "2.16.0") return undefined;
  const s = p.watermark.glyphShadow;
  if (!s) throw new Error("Film Type 2.11 requires explicit watermark glyph shadow tokens.");
  return shadowFilter(s);
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

/** 2.9 bounds the field by the frame, so the shadow never grows wider or taller
 * than the video. 2.10 goes further: one small soft field per measured row, so a
 * short line no longer drags a block-sized wash across the footage. */
const DiffuseField: React.FC<{layout:FilmMomentLayout;rows?:readonly FilmRow[];format:PersianFormat;design:PersianDesignSnapshot;opacity:number;travel:number;anchor:number;align:"left"|"right"|"center";peakMultiplier?:number}>=({layout,rows,format,design,opacity,travel,anchor,align,peakMultiplier=1})=>{
 const id=useId(),p=filmProfile(design),d=FORMAT_DIMENSIONS[format],cfg=p.contrast.diffuseField!;
 const dark=layout.contrastMode==="dark",peak=Math.min(.72,(layout.fieldPeakAlpha??p.contrast.strengths[layout.strength])*peakMultiplier);
 const bounded=p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || (p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0" || (p.profileVersion === "2.13.0" || p.profileVersion === "2.14.0" || (p.profileVersion === "2.15.0" || p.profileVersion === "2.16.0"))) ? {width:d.width,height:d.height} : undefined;
 const left=layout.rect.x*d.width, top=layout.rect.y*d.height;
 const fieldRows=rows ?? layout.rows;
 const fields=cfg.perRow
  ? fieldRows.map(row=>{
     const pad=cfg.rowPaddingPx??0, inkHeight=row.abovePx+row.belowPx;
     const {rx,ry}=diffuseRadii(row.widthPx+2*pad,inkHeight+2*pad,cfg,bounded);
     const rowAnchor=anchor+(row.offsetXPx??0);
     const rowRight=align==="center"?rowAnchor+row.widthPx/2:align==="left"?rowAnchor+row.widthPx:rowAnchor;
     return {rx,ry,cx:left+rowRight-row.widthPx/2,cy:top+row.baselinePx-row.abovePx+inkHeight/2+travel};
    })
  : [{...diffuseRadii(layout.widthPx,layout.heightPx,cfg,bounded),
      cx:(layout.rect.x+layout.rect.w/2)*d.width,cy:(layout.rect.y+layout.rect.h/2)*d.height+travel}];
 return <svg width={d.width} height={d.height} style={{position:"absolute",inset:0,opacity,zIndex:1,mixBlendMode:dark?"multiply":undefined,pointerEvents:"none"}} data-film-field-shape="diffuse" data-film-field-scope={cfg.perRow?"row":"block"}>
 <defs><radialGradient id={id}>{diffuseStops.map(s=><stop key={s.offset} offset={s.offset} stopColor={dark?p.contrast.darkField:p.contrast.lightField} stopOpacity={s.alpha*peak}/>)}</radialGradient></defs>
 {fields.map((f,i)=><ellipse key={i} cx={f.cx} cy={f.cy} rx={f.rx} ry={f.ry} fill={`url(#${id})`}/>)}</svg>;
};

/** #387 v3 poster hook: a full-width, vertically feathered dark band behind the
 * hook block only (never the whole frame), so the hook stays readable when the
 * footage under it turns bright. */
const PosterBand: React.FC<{layout:FilmMomentLayout;decor:FilmPosterDecor;format:PersianFormat;opacity:number;boost:number}>=({layout,decor,format,opacity,boost})=>{
 const id=useId(),d=FORMAT_DIMENSIONS[format];
 const top=Math.max(0,layout.rect.y*d.height-decor.band.padTopPx), bottom=Math.min(d.height,(layout.rect.y+layout.rect.h)*d.height+decor.band.padBottomPx);
 const alpha=Math.min(.68,decor.band.alpha*boost);
 // The flat core spans the whole text block; only the padding feathers out.
 const span=Math.max(1,bottom-top);
 const coreTop=clamp01((layout.rect.y*d.height-top)/span), coreBottom=clamp01(((layout.rect.y+layout.rect.h)*d.height-top)/span);
 return <svg data-film-poster-band="hook" width={d.width} height={d.height} style={{position:"absolute",inset:0,opacity,zIndex:1,pointerEvents:"none"}} aria-hidden="true">
  <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
   {/* Eased feather (smoothstep samples) so the band dissolves into the footage. */}
   {[0,.2,.4,.6,.8,1].map(t=><stop key={`t${t}`} offset={coreTop*t} stopColor="#000" stopOpacity={alpha*t*t*(3-2*t)}/>)}
   {[0,.2,.4,.6,.8,1].map(t=><stop key={`b${t}`} offset={coreBottom+(1-coreBottom)*t} stopColor="#000" stopOpacity={alpha*(1-t)*(1-t)*(1+2*t)}/>)}
  </linearGradient></defs>
  <rect x={0} y={top} width={d.width} height={bottom-top} fill={`url(#${id})`}/>
 </svg>;
};

/** Thin accent rule after the setup and a tapered brush stroke under the hero. */
const PosterOrnaments: React.FC<{decor:FilmPosterDecor;rows:readonly FilmRow[];anchor:number;align:"left"|"right"|"center";accent:string;progress:number;opacity:number}>=({decor,rows,anchor,align,accent,progress,opacity})=>{
 const id=useId(),p=Math.max(0,Math.min(1,progress));
 const centerOf=(row:FilmRow)=>{const a=anchor+(row.offsetXPx??0);return align==="center"?a:align==="right"?a-row.widthPx/2:a+row.widthPx/2;};
 const out:React.ReactNode[]=[];
 if(decor.divider){
  const dv=decor.divider,cx=centerOf(rows[dv.afterRow]),w=dv.widthPx*p;
  out.push(<rect key="divider" data-film-poster-ornament="divider" x={cx-w/2} y={dv.centerYPx-dv.thicknessPx/2} width={w} height={dv.thicknessPx} rx={dv.thicknessPx/2} fill={`url(#${id})`}/>);
 }
 if(decor.underline){
  const u=decor.underline,cx=centerOf(rows[u.underRow]),w=u.widthPx,h=u.heightPx;
  // RTL: the stroke is drawn from right to left as the hook arrives.
  const x1=cx+w/2,x0=x1-w*p,y=u.topPx;
  // Brush: a thin tip at the left, full body through the middle, a soft lift at the right.
  const mx=(x0+x1)/2;
  const path=`M ${x0} ${y+h*.72} C ${x0+(x1-x0)*.25} ${y+h*.30}, ${mx} ${y+h*.12}, ${x1} ${y} L ${x1} ${y+h*.55} C ${mx} ${y+h*.70}, ${x0+(x1-x0)*.25} ${y+h*.92}, ${x0} ${y+h} Z`;
  out.push(<path key="underline" data-film-poster-ornament="underline" d={path} fill={accent}/>);
 }
 return <g opacity={opacity*.96} aria-hidden="true">
  <defs><linearGradient id={id} x1="0" y1="0" x2="1" y2="0">
   <stop offset="0" stopColor={accent} stopOpacity={0}/><stop offset=".2" stopColor={accent} stopOpacity={1}/>
   <stop offset=".8" stopColor={accent} stopOpacity={1}/><stop offset="1" stopColor={accent} stopOpacity={0}/>
  </linearGradient></defs>
  {out}
 </g>;
};
const POSTER_GLYPH_SHADOW="drop-shadow(0 3px 5px rgba(0,0,0,.70)) drop-shadow(0 0 22px rgba(0,0,0,.50))";

const Run: React.FC<{row: FilmRow; x: number; color: string; accent: string; emphasis: boolean; semanticHero?: boolean; align?: "left" | "right" | "center"}> = ({row,x,color,accent,emphasis,semanticHero=false,align="right"}) => {
  const accents = new Set(row.accentWords.map(compareKey));
  const hasInlineAccent = emphasis && accents.size > 0;
  const baseFill = semanticHero && !hasInlineAccent ? accent : color;
  return <text data-film-type-ink={row.role} data-film-type-segment={row.segmentIndex}
    data-film-type-content={row.text} x={x} y={row.baselinePx}
    direction={row.direction} textAnchor={align === "center" ? "middle" : align === "right" ? (row.direction === "rtl" ? "start" : "end") : (row.direction === "rtl" ? "end" : "start")}
    style={{fontFamily:row.family,fontSize:row.fontSizePx,fontWeight:row.weight,letterSpacing:0,
      fontKerning:"normal",fontSynthesis:"none",unicodeBidi:"isolate",fill:baseFill}}>
    {hasInlineAccent ? row.text.split(/(\s+)/u).map((part,i) => {
      const highlighted=accents.has(compareKey(part));
      return <tspan key={i} style={highlighted ? {fill:accent} : undefined}>{part}</tspan>;
    }) : row.text}
  </text>;
};

const EditorialBurst: React.FC<{
  row: FilmRow; anchor: number; align: "left" | "right" | "center";
  accent: string; progress: number; opacity: number;
}> = ({row,anchor,align,accent,progress,opacity}) => {
  if (row.accentWords.length === 0) return null;
  const rightEdge = align === "center" ? anchor + row.widthPx / 2 : align === "right" ? anchor : anchor + row.widthPx;
  const ray = Math.max(30, Math.min(52, row.fontSizePx * .34));
  const x = rightEdge + Math.max(16, row.fontSizePx * .10);
  const y = Math.max(22, row.baselinePx - row.abovePx * .46);
  const p = Math.max(0, Math.min(1, progress));
  return <g data-film-editorial-accent="burst" opacity={opacity * .95} stroke={accent} strokeWidth={Math.max(4, row.fontSizePx * .034)} strokeLinecap="round">
    <line x1={x} y1={y - 7} x2={x + ray * .34 * p} y2={y - 7 - ray * .82 * p}/>
    <line x1={x + 4} y1={y + 5} x2={x + 4 + ray * .74 * p} y2={y + 5 - ray * .48 * p}/>
    <line x1={x + 2} y1={y + 18} x2={x + 2 + ray * .96 * p} y2={y + 18 - ray * .08 * p}/>
  </g>;
};


export const PersianFilmTypeMoment: React.FC<{
  moment: PersianMoment; layout: FilmMomentLayout; format: PersianFormat;
  durationFrames: number; design: PersianDesignSnapshot; shots: PersianVideoProps["shots"];
  hideGlyphs?: boolean; backdrop?: PersianVideoProps["filmTypeBackdrop"];
}> = ({moment,layout,format,durationFrames,design,shots,hideGlyphs=false,backdrop}) => {
  const frame = useCurrentFrame(), {fps} = useVideoConfig();
  const p = filmProfile(design), dims = FORMAT_DIMENSIONS[format];
  const kahrobaPromise = p.profileVersion === "2.16.0"
    ? ensureKahrobaReady(p.typography.editorial!.assetSha256)
    : null;
  const [kahrobaReady, setKahrobaReady] = useState(() => p.profileVersion !== "2.16.0" || isKahrobaLoaded());
  useEffect(() => {
    if (!kahrobaPromise || kahrobaReady) return;
    let active = true;
    kahrobaPromise.then(() => { if (active) setKahrobaReady(true); });
    return () => { active = false; };
  }, [kahrobaPromise, kahrobaReady]);
  const polished = isFilmTypePolish(design);
  if (!layout || layout.id !== moment.id) throw new Error(`Missing measured Film Type layout for ${moment.id}; run persian_compose.`);
  const span = durationFrames / fps, seconds = frame / fps;
  const absoluteSeconds = moment.startSeconds + seconds;
  const activeShot = shots.find(shot => absoluteSeconds >= shot.startSeconds && absoluteSeconds < shot.endSeconds);
  const busyBackground = p.profileVersion === "2.16.0" && activeShot?.visualComplexity === "busy";
  const fieldPeakMultiplier = (busyBackground ? 1.55 : 1) * backdropMultiplier(backdrop, moment.id, activeShot?.id);
  const firstReveal = Math.min(...layout.rows.map(row => row.revealAfterSeconds));
  const replaceSequence = moment.presentation?.sequenceMode === "replace";
  const sequenceReveals = replaceSequence
    ? [...new Set(layout.rows.map(row => row.revealAfterSeconds))].sort((a,b) => a-b)
    : [];
  const eligibleSequenceReveals = replaceSequence
    ? sequenceReveals.filter(at => at <= seconds + 1e-9)
    : [];
  const activeSequenceReveal = eligibleSequenceReveals.length
    ? eligibleSequenceReveals[eligibleSequenceReveals.length - 1]
    : undefined;
  const visibleRows = replaceSequence
    ? layout.rows.filter(row => row.revealAfterSeconds === activeSequenceReveal)
    : layout.rows;
  const modern=p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || (p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0" || (p.profileVersion === "2.13.0" || p.profileVersion === "2.14.0" || (p.profileVersion === "2.15.0" || p.profileVersion === "2.16.0")))))),lifeAt=modern?gentleLife:filmLife;
  const diffuse=p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || (p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0" || (p.profileVersion === "2.13.0" || p.profileVersion === "2.14.0" || (p.profileVersion === "2.15.0" || p.profileVersion === "2.16.0")));
  const fieldEnter=modern?(moment.presentation?.motion === "cut-in"?p.motion.cutInSeconds:p.motion.enterSeconds):p.motion.scrimEnterSeconds;
  const fieldLife = lifeAt(seconds,span,firstReveal,fieldEnter,p.motion.exitSeconds);
  const dark = layout.contrastMode === "dark";
  const color = p.profileVersion === "2.16.0" ? p.typography.editorial!.supportInk : (dark ? p.typography.ink : p.typography.darkInk);
  const accent = p.profileVersion === "2.16.0" ? p.typography.editorial!.semanticAccent : p.typography.accent;
  const cut = moment.presentation?.motion === "cut-in";
  const align = layout.placement === "center" || layout.placement.endsWith("-center") ? "center" : polished ? "right" : layout.placement.endsWith("left") ? "left" : "right";
  const anchor = align === "center" ? layout.widthPx/2 : align === "left" ? p.layout.inkPaddingPx : layout.widthPx-p.layout.inkPaddingPx;
  if (!kahrobaReady) return null;
  const decor = layout.posterDecor;
  return <AbsoluteFill data-film-type-moment={moment.id} data-film-type-placement={layout.placement} style={{pointerEvents:"none"}}>
    {busyBackground && !layout.subjectWrap ? <FilmContrastField rect={layout.rect} format={format} color={p.contrast.darkField}
      alpha={0.42} plateau={0.56} paddingPx={92} opacity={fieldLife.opacity} kind="text"/> : null}
    {decor ? <PosterBand layout={layout} decor={decor} format={format} opacity={fieldLife.opacity} boost={busyBackground ? 1.12 : 1}/> : diffuse ? <DiffuseField layout={layout} rows={visibleRows} format={format} design={design} opacity={fieldLife.opacity} travel={p.motion.travelPx*(1-fieldLife.arrive)} anchor={anchor} align={align} peakMultiplier={fieldPeakMultiplier}/> : modern ? <CompactFilmField featherPx={layout.fieldFeatherPx} rect={layout.rect} format={format} design={design} color={dark?p.contrast.darkField:p.contrast.lightField}
      alpha={p.contrast.strengths[layout.strength]} opacity={fieldLife.opacity} travel={p.motion.travelPx*(1-fieldLife.arrive)}/> : <FilmContrastField rect={layout.rect} format={format} color={dark?p.contrast.darkField:p.contrast.lightField}
      alpha={p.contrast.strengths[layout.strength]} plateau={p.contrast.plateauStop}
      paddingPx={p.contrast.plateauPaddingPx + p.motion.travelPx} opacity={fieldLife.opacity} kind="text"/>}
    <svg data-film-type-text={moment.id} width={layout.widthPx} height={layout.heightPx}
      viewBox={`0 0 ${layout.widthPx} ${layout.heightPx}`}
      data-film-background-complexity={busyBackground ? "busy" : "simple"}
      style={{position:"absolute",left:layout.rect.x*dims.width,top:layout.rect.y*dims.height,overflow:"visible",zIndex:2,filter:decor ? POSTER_GLYPH_SHADOW : glyphShadowFilter(p,busyBackground)}}>
      {decor ? <PosterOrnaments decor={decor} rows={layout.rows} anchor={anchor} align={align} accent={accent} progress={fieldLife.arrive} opacity={fieldLife.opacity}/> : null}
      {layout.rows.map((row,index) => {
        if (replaceSequence && row.revealAfterSeconds !== activeSequenceReveal) return null;
        // A quantity and its unit share the same authored segment and entrance.
        // Later authored reveal times are never pulled forward or silently lost.
        const delay = filmRowDelay(row,p);
        const life = replaceSequence
          ? {arrive:1,leave:clamp01((span-seconds)/Math.max(.001,p.motion.exitSeconds)),opacity:clamp01((span-seconds)/Math.max(.001,p.motion.exitSeconds))}
          : lifeAt(seconds,span,delay,cut?p.motion.cutInSeconds:p.motion.enterSeconds,p.motion.exitSeconds);
        const y = replaceSequence || (cut && !modern) ? 0 : p.motion.travelPx * (1-life.arrive);
        const accented216 = p.profileVersion === "2.16.0" && row.accentWords.length > 0;
        const punch = accented216 ? .985 + .015 * life.arrive : 1;
        const rowAnchor = anchor + (row.offsetXPx ?? 0);
        const transform = `translate(0 ${y}) translate(${rowAnchor} 0) scale(${punch}) translate(${-rowAnchor} 0)`;
        const segmentHasSemanticAccent = (moment.segments[row.segmentIndex]?.accentWords?.length ?? 0) > 0;
        return <g key={index} data-film-type-row={index} opacity={life.opacity} transform={transform}>
          {hideGlyphs ? null : <Run row={row} x={rowAnchor} align={align} color={color} accent={accent} semanticHero={p.profileVersion === "2.16.0" && row.role === "hero" && !segmentHasSemanticAccent} emphasis={moment.presentation?.emphasis === "inline"}/>}
          {accented216 && moment.kind !== "hook" ? <EditorialBurst row={row} anchor={rowAnchor} align={align} accent={accent} progress={life.arrive} opacity={life.opacity}/> : null}
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
  const opacity=p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || (p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0" || (p.profileVersion === "2.13.0" || p.profileVersion === "2.14.0" || (p.profileVersion === "2.15.0" || p.profileVersion === "2.16.0")))))) ? gentleLife(seconds-entry.startSeconds,entry.endSeconds-entry.startSeconds,0,p.watermark.transitionSeconds,p.watermark.transitionSeconds).opacity
    : Math.min(1,(seconds-entry.startSeconds)/p.watermark.transitionSeconds,(entry.endSeconds-seconds)/p.watermark.transitionSeconds);
  const align = entry.zone.endsWith("left") ? "left" : "right";
  const anchor = align === "left" ? p.watermark.paddingPx : lockup.widthPx-p.watermark.paddingPx;
  return <AbsoluteFill data-film-type-brand={entry.zone} style={{pointerEvents:"none"}}>
    {!polished && <FilmContrastField rect={entry.rect} format={format} color={p.contrast.darkField} alpha={p.watermark.fieldAlpha}
      plateau={p.contrast.plateauStop} paddingPx={p.watermark.fieldPaddingPx} opacity={opacity} kind="brand"/>}
    <svg data-film-type-watermark="lockup" width={lockup.widthPx} height={lockup.heightPx}
      viewBox={`0 0 ${lockup.widthPx} ${lockup.heightPx}`}
      style={{position:"absolute",left:entry.rect.x*dims.width,top:entry.rect.y*dims.height,overflow:"visible",opacity,zIndex:3,filter:(p.profileVersion === "2.11.0" || p.profileVersion === "2.12.0" || (p.profileVersion === "2.13.0" || p.profileVersion === "2.14.0" || (p.profileVersion === "2.15.0" || p.profileVersion === "2.16.0"))) ? watermarkGlyphShadowFilter(p) : glyphShadowFilter(p)}}>
      {lockup.rows.map((row,index)=><Run key={index} row={row} x={anchor} align={align} color={p.typography.ink} accent={p.typography.accent} emphasis={false}/>)}
    </svg>
  </AbsoluteFill>;
};
