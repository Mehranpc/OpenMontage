import {diffuseRadii,diffuseStops} from "./diffuse27";
/** Film Type paint. All movement is frame-driven; no CSS animation/timers. */
import React, { useEffect, useId, useMemo, useState } from "react";
import { AbsoluteFill, Easing, useCurrentFrame, useVideoConfig } from "remotion";
import { compareKey } from "../text";
import { ensureKahrobaReady, ensureVazirmatnReady, isKahrobaLoaded, isVazirmatnLoaded } from "../fonts";
import { DesignedHookPaint } from "./designedHook";
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

/** #387 v3 poster hook: a soft elliptical glow behind the hook block only. It is
 * darkest behind the text and dissolves on every side (no band edges), so the hook
 * stays readable over bright footage without a visible box. */
const smooth01=(e0:number,e1:number,x:number)=>{const t=clamp01((x-e0)/Math.max(1e-6,e1-e0));return t*t*(3-2*t);};
const POSTER_GLOW_STOPS=Array.from({length:17},(_,i)=>i/16);
const PosterBand: React.FC<{layout:FilmMomentLayout;decor:FilmPosterDecor;format:PersianFormat;opacity:number;boost:number}>=({layout,decor,format,opacity,boost})=>{
 const id=useId(),d=FORMAT_DIMENSIONS[format];
 const alpha=Math.min(.78,decor.band.alpha*boost);
 const blockW=layout.rect.w*d.width, blockH=layout.rect.h*d.height;
 const cx=(layout.rect.x+layout.rect.w/2)*d.width, cy=(layout.rect.y+layout.rect.h*.44)*d.height;
 const rx=Math.max(d.width*.62,blockW*.78), ry=blockH*.56+(decor.band.padTopPx+decor.band.padBottomPx)*.85;
 return <svg data-film-poster-band="hook" data-film-poster-band-shape="glow" width={d.width} height={d.height} style={{position:"absolute",inset:0,opacity,zIndex:1,pointerEvents:"none"}} aria-hidden="true">
  <defs><radialGradient id={id} cx="50%" cy="50%" r="50%">
   {POSTER_GLOW_STOPS.map(t=><stop key={t} offset={t} stopColor="#000" stopOpacity={alpha*(1-smooth01(.30,1,t))}/>)}
  </radialGradient></defs>
  <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill={`url(#${id})`}/>
 </svg>;
};

/** Deterministic PRNG so every render of the same hook paints the same brush. */
const brushRandom=(seedText:string)=>{let h=2166136261;for(const ch of seedText){h^=ch.codePointAt(0)!;h=Math.imul(h,16777619);}
 let a=h>>>0;return ()=>{a=(a+0x6D2B79F5)>>>0;let t=a;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return ((t^(t>>>14))>>>0)/4294967296;};};
const pathOf=(top:readonly [number,number][],bottom:readonly [number,number][])=>
 `M ${top.map(([x,y])=>`${x.toFixed(1)} ${y.toFixed(1)}`).join(" L ")} L ${[...bottom].reverse().map(([x,y])=>`${x.toFixed(1)} ${y.toFixed(1)}`).join(" L ")} Z`;

/** Tapered accent rule: thick in the middle, hair-thin and faded at both ends. */
const dividerPath=(cx:number,cy:number,w:number,t:number)=>{
 const n=40,top:[number,number][]=[],bottom:[number,number][]=[];
 for(let i=0;i<=n;i++){const u=i/n,half=t/2*Math.pow(Math.sin(Math.PI*u),1.6),x=cx-w/2+w*u;top.push([x,cy-half]);bottom.push([x,cy+half]);}
 return pathOf(top,bottom);
};

/** Hand-painted brush stroke (RTL: loaded at the right, dry bristles trailing left). */
const brushStroke=(x0:number,x1:number,y:number,h:number,seed:string)=>{
 const rnd=brushRandom(seed),w=x1-x0,n=72;
 // Rises to the right like a hand stroke (about 3.5 degrees), body sits below the hero.
 const centre=(u:number)=>y+h*.85+w*.03-w*.06*u+h*.08*Math.sin(Math.PI*u);
 const half=(u:number)=>h*.47*(.22+.78*smooth01(0,.26,u))*(1-.80*smooth01(.80,1,u));
 const top:[number,number][]=[],bottom:[number,number][]=[];
 for(let i=0;i<=n;i++){const u=i/n,x=x0+w*u,c=centre(u),k=half(u);
  top.push([x,c-k+h*.13*(rnd()-.5)]);bottom.push([x,c+k+h*.13*(rnd()-.5)]);}
 const body=pathOf(top,bottom);
 // Dry gaps: hairline scratches cut through the trailing (left) part of the body.
 const scratches:{d:string;width:number}[]=[];
 for(let i=0;i<4;i++){const off=(i+.5)/4-.5+(rnd()-.5)*.10,len=.16+.18*rnd(),u1=len;
  const pts=[0,.25,.5,.75,1].map(f=>{const u=u1*f;return `${(x0+w*u-w*.06).toFixed(1)} ${(centre(u)+off*2*half(u)).toFixed(1)}`;});
  scratches.push({d:`M ${pts.join(" L ")}`,width:Math.max(1.2,h*(.025+.025*rnd()))});}
 // Loose bristles that run past the body's dry end.
 const bristles:string[]=[];
 for(let i=0;i<7;i++){const off=(rnd()-.5)*1.5,ext=w*(.03+.10*rnd()),start=.08+.10*rnd(),th=Math.max(1.2,h*(.05+.06*rnd()));
  const cy0=centre(start)+off*half(start),xs=x0+w*start,xe=x0-ext,cye=cy0+h*.06*(rnd()-.5)+h*.08;
  bristles.push(`M ${xs.toFixed(1)} ${(cy0-th/2).toFixed(1)} Q ${((xs+xe)/2).toFixed(1)} ${(cy0-th*.4).toFixed(1)} ${xe.toFixed(1)} ${cye.toFixed(1)} Q ${((xs+xe)/2).toFixed(1)} ${(cy0+th*.4).toFixed(1)} ${xs.toFixed(1)} ${(cy0+th/2).toFixed(1)} Z`);}
 return {body,scratches,bristles,minX:x0-w*.14};
};

const PosterOrnaments: React.FC<{decor:FilmPosterDecor;rows:readonly FilmRow[];anchor:number;align:"left"|"right"|"center";accent:string;progress:number;opacity:number}>=({decor,rows,anchor,align,accent,progress,opacity})=>{
 const id=useId().replace(/:/g,""),p=Math.max(0,Math.min(1,progress));
 const centerOf=(row:FilmRow)=>{const a=anchor+(row.offsetXPx??0);return align==="center"?a:align==="right"?a-row.widthPx/2:a+row.widthPx/2;};
 const out:React.ReactNode[]=[],defs:React.ReactNode[]=[];
 if(decor.divider){
  const dv=decor.divider,cx=centerOf(rows[dv.afterRow]),w=Math.max(1,dv.widthPx*p);
  out.push(<path key="divider" data-film-poster-ornament="divider" data-film-poster-divider-shape="tapered" d={dividerPath(cx,dv.centerYPx,w,dv.thicknessPx)} fill={`url(#${id}-fade)`}/>);
 }
 if(decor.underline){
  const u=decor.underline,row=rows[u.underRow],cx=centerOf(row),w=u.widthPx,h=u.heightPx;
  const x1=cx+w/2,x0=x1-w;
  const brush=brushStroke(x0,x1,u.topPx,h,row.text);
  // RTL reveal: the stroke is painted from right to left as the hook arrives.
  const revealX=x1-(x1-brush.minX)*p;
  defs.push(<clipPath key="clip" id={`${id}-reveal`}><rect x={revealX} y={u.topPx-h*2} width={x1+h-revealX} height={h*5}/></clipPath>);
  defs.push(<mask key="mask" id={`${id}-dry`} maskUnits="userSpaceOnUse" x={brush.minX-h} y={u.topPx-h*2} width={w*1.3+2*h} height={h*5}>
   <rect x={brush.minX-h} y={u.topPx-h*2} width={w*1.3+2*h} height={h*5} fill="#000"/>
   <path d={brush.body} fill="#fff"/>{brush.bristles.map((d,i)=><path key={i} d={d} fill="#fff"/>)}
   {brush.scratches.map((s,i)=><path key={`s${i}`} d={s.d} stroke="#000" strokeWidth={s.width} strokeLinecap="round" fill="none"/>)}
  </mask>);
  out.push(<g key="underline" data-film-poster-ornament="underline" data-film-poster-underline-shape="brush" clipPath={`url(#${id}-reveal)`}>
   <rect x={brush.minX-h} y={u.topPx-h*2} width={w*1.3+2*h} height={h*5} fill={accent} mask={`url(#${id}-dry)`}/>
  </g>);
 }
 return <g opacity={opacity*.96} aria-hidden="true">
  <defs><linearGradient id={`${id}-fade`} x1="0" y1="0" x2="1" y2="0">
   <stop offset="0" stopColor={accent} stopOpacity={0}/><stop offset=".3" stopColor={accent} stopOpacity={.85}/><stop offset=".5" stopColor={accent} stopOpacity={1}/>
   <stop offset=".7" stopColor={accent} stopOpacity={.85}/><stop offset="1" stopColor={accent} stopOpacity={0}/>
  </linearGradient>{defs}</defs>
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
  const designedHook = layout?.designedHook;
  const vazirmatnPromise = designedHook ? ensureVazirmatnReady() : null;
  const [vazirmatnReady, setVazirmatnReady] = useState(() => !designedHook || isVazirmatnLoaded());
  useEffect(() => {
    if (!vazirmatnPromise || vazirmatnReady) return;
    let active = true;
    vazirmatnPromise.then(() => { if (active) setVazirmatnReady(true); });
    return () => { active = false; };
  }, [vazirmatnPromise, vazirmatnReady]);
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
  if (!kahrobaReady || !vazirmatnReady) return null;
  // #387 v3: Mehran's approved opening hook, static from its first frame (no animation).
  if (designedHook) return <DesignedHookPaint momentId={moment.id} hook={designedHook} hideGlyphs={hideGlyphs}/>;
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
