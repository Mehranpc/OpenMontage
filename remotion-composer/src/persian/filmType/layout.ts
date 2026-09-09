import { diffuseRadii, diffuseAt } from "./diffuse27";
/** Opt-in Film Type: full shaped runs, real ink baselines, one frozen layout.
 * No imports from the Legacy fitter: its sizing, word spans and silhouette are
 * deliberately unchanged. The same browser measurement feeds paint and planning.
 */
import { planMovingBrand } from "./watermark24";
import { estedadReady, isEstedadLoaded, ESTEDAD_FAMILY } from "../fonts";
import { breakClass, splitWords, visibleLength } from "../text";
import { FORMAT_DIMENSIONS, MOMENT_READ_CPS, MOMENT_FIXATION_SECONDS, MOMENT_BLOCK_SECONDS, MOMENT_SOURCE_READ_WEIGHT, MOMENT_MIN_SECONDS, type PersianFormat } from "../tokens";
import { assertMomentIsWellFormed, DEFAULT_WATERMARK, type PersianMoment,
  type PersianVideoProps, type PersianDesignSnapshot } from "../types";

export type Rect = { x: number; y: number; w: number; h: number };
export type AvoidRegion = Rect & { startSeconds?: number; endSeconds?: number };
export type Strength = "soft" | "standard" | "strong";
export type FilmProfile = {
  profile: "film-type"; profileVersion: "2.1.0" | "2.2.0" | "2.3.0" | "2.4.0" | "2.5.0" | "2.6.0" | "2.7.0" | "2.8.0" | "2.9.0" | "2.10.0" | "2.11.0"; layoutVersion: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11;
  formats: Record<PersianFormat, { safeArea: {top: number; bottom: number; side: number; left?:number; right?:number}; columnFraction: number; wideColumnFraction: number }>;
  typography: { fontFamily: string; heroWeight: 700; supportWeight: 500; ink: string; darkInk: string; accent: string;
    titleLadderPx: number[]; statementLadderPx: number[]; figureLadderPx: number[];
    titleTailRatio: number; contextPx: number; supportPx: number; sourcePx: number; quantityUnitPx: number };
  layout: {inkPaddingPx: number; lineGapPx: number; phraseGapPx: number; contextGapPx: number; sourceGapPx: number;
    quantityGapPx: number; revealGroupGapPx: number; maxStackFraction: number; edgeInsetPx: number;
    upperCentre: number; middleCentre: number; motionClearancePx: number; collisionMarginPx: number; autoRequiresReviewedAvoidRegions: boolean; aestheticPolicy?: "ranked-v1"; safeAreaPaddingPx?: number};
    contrast: {darkField: string; lightField: string; strengths: Record<Strength, number>; defaultStrength: Strength;
    diffuseField?: {radiusScale:number;minRadiusPx:number;maxSubjectAlpha:number;perRow?:boolean;rowPaddingPx?:number};
    // 2.10 separates letter edges at the glyph, so the field can stay small.
    glyphShadow?: {color:string;nearOffsetPx:number;nearBlurPx:number;nearAlpha:number;haloBlurPx:number;haloAlpha:number};
    compactField?: {paddingPx:number; featherPx:number; exponent:number; steps:number; blend?: "multiply" | "source-over"; featherCurve?: number};
    plateauStop: number; plateauPaddingPx: number; footageGrade: "none"};
  motion: {enterSeconds: number; exitSeconds: number; travelPx: number; lineDelaySeconds: number; cutInSeconds: number; scrimEnterSeconds: number};
  watermark: {persianFontPx: number; latinFontPx: number; latinFontFamily: string; latinWeight: 400;
    lineGapPx: number; paddingPx: number; maxRelocations: number; minDwellSeconds: number;
    transitionSeconds: number; preferNonTopPosition: boolean; fieldAlpha: number; fieldPaddingPx: number;
    introDelaySeconds?: number;
    safeAreas?: Record<PersianFormat, {top: number; bottom: number; left: number; right: number}>;
    targetDwellSeconds?: number; allowedZones?: string[]; preferStablePosition?: boolean; pairWithText?: boolean;
    glyphShadow?: {color:string;nearOffsetPx:number;nearBlurPx:number;nearAlpha:number;haloBlurPx:number;haloAlpha:number}};
};
export type FilmRow = {
  text: string; role: string; segmentIndex: number; fontSizePx: number; weight: 400 | 500 | 700;
  family: string; direction: "rtl" | "ltr"; abovePx: number; belowPx: number;
  widthPx: number; baselinePx: number; revealAfterSeconds: number; accentWords: readonly string[];
};
export type FilmMomentLayout = {
  id: string; rows: FilmRow[]; widthPx: number; heightPx: number; rect: Rect;
  placement: string; subjectSafety: "checked-against-supplied-regions" | "not-checked";
  contrastMode: "dark" | "light"; strength: Strength; fieldFeatherPx?: number; fieldPeakAlpha?: number;
};
export type FilmLockup = {rows: FilmRow[]; widthPx: number; heightPx: number; layout: "two-line"; measured: true};
export type FilmTypeLayout = {
  version: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11; inputHash: string; moments: Record<string, FilmMomentLayout>;
  lockup: FilmLockup | null; warnings: string[];
};
type TimedRect = Rect & { startSeconds: number; endSeconds: number };

const round = (n: number) => Math.round(n * 1000) / 1000;
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
export function isFilmType(design?: PersianDesignSnapshot): boolean {
  if(design?.profile==="film-type"&&design.version!==2) throw new Error("Film Type requires explicit design.version=2; no Legacy fallback.");
  return design?.version===2&&design.profile==="film-type";
}
export function isFilmTypePolish(design?: PersianDesignSnapshot): boolean {
  return (
    design !== undefined &&
    isFilmType(design) &&
    (design.profileVersion === "2.2.0" ||
      design.profileVersion === "2.3.0" || design.profileVersion === "2.4.0" || (design.profileVersion === "2.5.0" || (design.profileVersion === "2.6.0" || (design.profileVersion === "2.7.0" || design.profileVersion === "2.8.0" || design.profileVersion === "2.9.0" || design.profileVersion === "2.10.0" || design.profileVersion === "2.11.0"))))
  );
}
export function stableJSON(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJSON).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).filter(([,v]) => v !== undefined).sort(([a],[b]) => a < b ? -1 : a > b ? 1 : 0).map(([k,v]) => `${JSON.stringify(k)}:${stableJSON(v)}`).join(",")}}`;
  return JSON.stringify(value);
}
export async function sha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(stableJSON(value));
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(n => n.toString(16).padStart(2,"0")).join("");
}
export function filmProfile(design: PersianDesignSnapshot): FilmProfile {
  const p = design.resolved as unknown as FilmProfile;
  if (!isFilmType(design) || !p || p.profile !== "film-type" || !((p.profileVersion === "2.1.0" && p.layoutVersion === 1) || (p.profileVersion === "2.2.0" && p.layoutVersion === 2) || (p.profileVersion === "2.3.0" && p.layoutVersion === 3) || (p.profileVersion === "2.4.0" && p.layoutVersion === 4) || (p.profileVersion === "2.5.0" && p.layoutVersion === 5) || (p.profileVersion === "2.6.0" && p.layoutVersion === 6) || (p.profileVersion === "2.7.0" && p.layoutVersion === 7) || (p.profileVersion === "2.8.0" && p.layoutVersion === 8) || (p.profileVersion === "2.9.0" && p.layoutVersion === 9) || (p.profileVersion === "2.10.0" && p.layoutVersion === 10) || (p.profileVersion === "2.11.0" && p.layoutVersion === 11)) || design.profileVersion !== p.profileVersion) {
    throw new Error("Unsupported Film Type snapshot. Re-prepare with an explicitly supported profile; do not fall back to Legacy.");
  }
  if(typeof design.seed!=="string"||!design.seed.trim()) throw new Error("Film Type requires a non-empty deterministic seed.");
  if (p.typography.fontFamily !== ESTEDAD_FAMILY) throw new Error("Film Type requires the vendored Estedad family.");
  if ((p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0") && !p.contrast.glyphShadow) throw new Error("Film Type 2.10 requires explicit glyph shadow tokens.");
  return p;
}

let canvas: CanvasRenderingContext2D | null = null;
const measurements = new Map<string, {abovePx: number; belowPx: number; widthPx: number}>();
/** Measure the ORIGINAL run, including its ZWNJ. Paint does not split letters or
 * put words in flex boxes, so there is no estimated ZWNJ/notdef surcharge. */
export function measureRun(text: string, size: number, weight: number, family = ESTEDAD_FAMILY, direction: "rtl" | "ltr" = "rtl") {
  if (!isEstedadLoaded()) throw new Error("Film Type measurement requires loaded Estedad fonts.");
  const key = stableJSON([text,size,weight,family,direction]);
  const cached = measurements.get(key);
  if (cached) return cached;
  if (!canvas) canvas = document.createElement("canvas").getContext("2d");
  if (!canvas) throw new Error("Film Type requires a real browser canvas; estimates are not accepted.");
  canvas.font = `${weight} ${size}px "${family}"`;
  canvas.textBaseline = "alphabetic";
  canvas.textAlign = "right";
  canvas.direction = direction;
  const m = canvas.measureText(text);
  if (![m.width,m.actualBoundingBoxAscent,m.actualBoundingBoxDescent,m.actualBoundingBoxLeft,m.actualBoundingBoxRight].every(Number.isFinite)) {
    throw new Error("Browser did not return actual glyph bounds. Film Type refuses estimated ink geometry.");
  }
  const result = {abovePx: round(Math.max(0,m.actualBoundingBoxAscent)), belowPx: round(Math.max(0,m.actualBoundingBoxDescent)),
    widthPx: round(Math.max(m.width,m.actualBoundingBoxLeft + m.actualBoundingBoxRight) + 2)};
  measurements.set(key,result);
  return result;
}

/** DP over whole shaped runs; reuse the Persian grammar rules, not the Legacy
 * word-span sizing. Forced newlines remain forced and cannot strand a clitic. */
export function breakFilmLines(text: string, width: number, size: number, weight: number, maxLines: number, version: FilmProfile["profileVersion"] = "2.1.0"): string[] | null {
  const words = splitWords(text);
  if (!words.length) throw new Error("Film Type received an empty text run.");
  const memo = new Map<string, {cost: number; lines: string[]} | null>();
  const solve = (at: number, remaining: number): {cost: number; lines: string[]} | null => {
    while (words[at] === "\n") at++;
    if (at >= words.length) return {cost: 0, lines: []};
    if (!remaining) return null;
    const key = `${at}:${remaining}`;
    if (memo.has(key)) return memo.get(key)!;
    let best: {cost: number; lines: string[]} | null = null;
    for (let end = at; end < words.length && words[end] !== "\n"; end++) {
      const line = words.slice(at,end + 1).join(" ");
      const measured = measureRun(line,size,weight).widthPx;
      if (measured > width) continue;
      const next = words[end + 1] === "\n" ? words[end + 2] : words[end + 1];
      let boundary = breakClass(words[end],next ?? null);
      const prefix = (word: string | undefined) => word === "قبل" || word === "بعد" || word === "پیش";
      // Versioned rules: 2.1 retains its original wrapping; 2.2 retains the
      // shipped (over-binding) rule. Never modify shared Legacy/quiet grammar.
      if (version !== "2.1.0" && next === "از" && prefix(words[end])) boundary = "forbidden";
      // A COMPLETE display prefix may end a line: «قبل از» / «بعد از» / «پیش از».
      // Re-check backward binding with a neutral preceding token so «را» and
      // light verbs cannot be orphaned by this contextual exception. Do not
      // insert NBSP/newlines or rewrite the authored segment to force fitting.
      if ((version === "2.3.0" || version === "2.4.0" || (version === "2.5.0" || (version === "2.6.0" || (version === "2.7.0" || version === "2.8.0" || version === "2.9.0" || version === "2.10.0" || version === "2.11.0")))) && end > at && words[end] === "از" && prefix(words[end - 1])
          && breakClass("—", next ?? null) !== "forbidden") boundary = "preferred";
      if (next && boundary === "forbidden") continue;
      const rest = solve(end + 1,remaining - 1);
      if (!rest) continue;
      const slack = width - measured;
      const cost = (version === "2.6.0" || (version === "2.7.0" || version === "2.8.0" || version === "2.9.0" || version === "2.10.0" || version === "2.11.0"))
        ? rest.cost + 1 + Math.pow(slack / width, 2) * .7
          + (next && end === at ? .65 : 0)
          + (next && boundary !== "preferred" ? .08 : 0)
        : rest.cost + (rest.lines.length ? slack * slack * (boundary === "preferred" ? .85 : 1) : 0);
      if (!best || cost < best.cost) best = {cost, lines: [line,...rest.lines]};
    }
    memo.set(key,best);
    return best;
  };
  return solve(0,maxLines)?.lines ?? null;
}

/** A display split is an internal rendering of ONE authored hero, never a new
 * `unit` field, reordered content, a detached satellite, or an invented quantity. */
export function splitQuantity(text: string): [string,string] | null {
  if (/\r|\n/.test(text)) return null; // Deliberate line breaks remain authored.
  const match = text.trim().match(/^([۰-۹٠-٩ 0-9]+(?:[٬,٫.][۰-۹٠-٩ 0-9]+)*(?:[٪%])?)\s+(.+)$/u);
  return match && !match[2].includes("\n") ? [match[1],match[2]] : null;
}

function fitAtWidth(moment: PersianMoment, p: FilmProfile, fmt: PersianFormat, column: number, selectedSize?: number): Omit<FilmMomentLayout,"rect"|"placement"|"subjectSafety"|"contrastMode"|"strength"> | null {
  const t = p.typography, l = p.layout, dims = FORMAT_DIMENSIONS[fmt];
  const numeric = moment.kind === "figure" && moment.segments.some(s => s.role === "hero" && splitQuantity(s.text));
  const ladder = numeric ? t.figureLadderPx : moment.kind === "hook" ? t.titleLadderPx : t.statementLadderPx;
  const safe = p.formats[fmt].safeArea;
  const maxHeight = dims.height * (1 - safe.top - safe.bottom) * l.maxStackFraction;
  for (const main of selectedSize === undefined ? ladder : [selectedSize]) {
    let y = l.inkPaddingPx, widest = 0, failed = false;
    const rows: FilmRow[] = [];
    let previousReveal = 0;
    for (let index = 0; index < moment.segments.length; index++) {
      const segment = moment.segments[index];
      const reveal = segment.revealAfterSeconds ?? 0;
      if (index) y += reveal > previousReveal ? l.revealGroupGapPx : segment.role === "source" ? l.sourceGapPx : segment.role === "hero" && moment.segments[index - 1].role === "lead" ? l.contextGapPx : l.phraseGapPx;
      previousReveal = reveal;
      const quantity = numeric && segment.role === "hero" ? splitQuantity(segment.text) : null;
      const pieces = quantity ? [
        {text: quantity[0], role: "quantity", size: main, weight: 500 as const, max: 1},
        {text: quantity[1], role: "quantity-unit", size: t.quantityUnitPx, weight: 500 as const, max: 2},
      ] : [{text: segment.text, role: segment.role,
        size: segment.role === "source" ? t.sourcePx : segment.role === "lead" ? t.contextPx : segment.role === "tail" ? (moment.kind === "hook" ? Math.round(main * t.titleTailRatio) : t.supportPx) : main,
        weight: (segment.role === "hero" ? t.heroWeight : t.supportWeight),
        max: segment.role === "hero" ? 3 : 2}];
      for (const [pieceIndex,piece] of pieces.entries()) {
        if (pieceIndex) y += l.quantityGapPx;
        const lines = breakFilmLines(piece.text,column - 2 * l.inkPaddingPx,piece.size,piece.weight,piece.max,p.profileVersion);
        if (!lines) {failed = true; break;}
        for (const [lineIndex,text] of lines.entries()) {
          if (lineIndex) y += l.lineGapPx;
          const ink = measureRun(text,piece.size,piece.weight);
          const underline = moment.presentation?.emphasis === "inline" && (segment.accentWords?.length ?? 0) > 0;
          const belowPx = Math.max(ink.belowPx,underline ? piece.size * .14 : 0);
          rows.push({text,role: piece.role,segmentIndex: index,fontSizePx: piece.size,weight: piece.weight,
            family: ESTEDAD_FAMILY,direction: "rtl",...ink,belowPx: round(belowPx),baselinePx: round(y + ink.abovePx),
            revealAfterSeconds: reveal,accentWords: segment.accentWords ?? []});
          y += ink.abovePx + belowPx;
          widest = Math.max(widest,ink.widthPx);
        }
      }
      if (failed) break;
    }
    if (!failed && y + l.inkPaddingPx <= maxHeight) return {id: moment.id,rows,widthPx: Math.ceil(widest + l.inkPaddingPx * 2),heightPx: Math.ceil(y + l.inkPaddingPx)};
  }
  return null;
}

export function intersects(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}
function expand(r: Rect, x: number, y: number): Rect {return {x:r.x-x,y:r.y-y,w:r.w+2*x,h:r.h+2*y};}
/** 2.11 keeps text one extra margin inside the frozen safe area. Older pins never
 * carried the token, so their geometry is unchanged. */
function safePadPx(p: FilmProfile): number {
  return p.profileVersion === "2.11.0" ? (p.layout.safeAreaPaddingPx ?? 0) : 0;
}
function inSafe(r: Rect, s: {top:number; bottom:number; side:number;left?:number;right?:number}, padX = 0, padY = 0): boolean {
  return r.x >= (s.left??s.side) + padX - 1e-8 && r.y >= s.top + padY - 1e-8 && r.x + r.w <= 1 - (s.right??s.side) - padX + 1e-8 && r.y + r.h <= 1 - s.bottom - padY + 1e-8;
}
export function timedAvoidRegions(props: PersianVideoProps): TimedRect[] {
  const result: TimedRect[] = [];
  for (const shot of props.shots) {
    if (shot.avoidRegions !== undefined && !Array.isArray(shot.avoidRegions)) throw new Error(`Shot ${shot.id}: avoidRegions must be an array.`);
    for (const region of shot.avoidRegions ?? []) {
      if (![region.x,region.y,region.w,region.h].every(Number.isFinite) || region.x < 0 || region.y < 0 || region.w <= 0 || region.h <= 0 || region.x + region.w > 1 || region.y + region.h > 1) throw new Error(`Shot ${shot.id}: invalid normalized avoid region.`);
      const start = region.startSeconds ?? shot.startSeconds, end = region.endSeconds ?? shot.endSeconds;
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || start < shot.startSeconds || end > shot.endSeconds) throw new Error(`Shot ${shot.id}: avoid region times must be absolute timeline seconds within this shot.`);
      result.push({...region,startSeconds:start,endSeconds:end});
    }
  }
  return result;
}

/** One timing rule is consumed by both preparation and paint. Authored delayed
 * segments and all sources start at their exact reveal time, without an added
 * decorative delay. Reject unreadable windows; never change approved timings. */
export function filmRowDelay(row: Pick<FilmRow,"revealAfterSeconds"|"segmentIndex"|"role">, p: FilmProfile): number {
  return row.revealAfterSeconds + (row.revealAfterSeconds > 0 || row.role === "source" ? 0 : Math.min(row.segmentIndex*p.motion.lineDelaySeconds,.18));
}
function assertFilmTiming(moment: PersianMoment, p: FilmProfile): void {
  const span=moment.endSeconds-moment.startSeconds;
  if(span<MOMENT_MIN_SECONDS) throw new Error(`Moment ${moment.id}: Film Type needs at least ${MOMENT_MIN_SECONDS}s; short flashes are not readable.`);
  const starts=[...new Set(moment.segments.map(s=>s.revealAfterSeconds??0))].sort((a,b)=>a-b);
  for(const [i,start] of starts.entries()){
    const group=moment.segments.map((s,index)=>({s,index})).filter(({s})=>(s.revealAfterSeconds??0)===start);
    const delay=Math.max(...group.map(({s,index})=>filmRowDelay({role:s.role,segmentIndex:index,revealAfterSeconds:start},p)-start));
    const enter=moment.presentation?.motion==="cut-in"?p.motion.cutInSeconds:p.motion.enterSeconds;
    const chars=group.reduce((sum,{s})=>sum+visibleLength(s.text)*(s.role==="source"?MOMENT_SOURCE_READ_WEIGHT:1),0);
    const blocks=group.filter(({s})=>s.role!=="source").length;
    const exit=i===starts.length-1?p.motion.exitSeconds:0;
    const needed=delay+Math.max(MOMENT_FIXATION_SECONDS,enter)+chars/MOMENT_READ_CPS+Math.max(0,blocks-1)*MOMENT_BLOCK_SECONDS+exit;
    const available=(starts[i+1]??span)-start;
    if(available+1e-6<needed) throw new Error(`Moment ${moment.id}: reveal at +${start}s (including any source) needs ${needed.toFixed(3)}s but has ${available.toFixed(3)}s. Re-edit/re-time explicitly; no source was hidden or rushed.`);
  }
}

function placeMoment(moment: PersianMoment, props: PersianVideoProps, p: FilmProfile, avoid: TimedRect[]): FilmMomentLayout {
  assertMomentIsWellFormed(moment);
  assertFilmTiming(moment,p);
  if(moment.presentation!==undefined && (!moment.presentation || typeof moment.presentation!=="object" || Array.isArray(moment.presentation))) throw new Error(`Moment ${moment.id}: Film Type presentation must be an object.`);
  const presentation=moment.presentation??{};
  for(const [key,allowed] of Object.entries({treatment:["editorial","inline-statement"],motion:["soft-reveal","cut-in"],emphasis:["none","inline"]})){
    const value=(presentation as Record<string,unknown>)[key];
    if(value!==undefined&&!allowed.includes(value as string)) throw new Error(`Moment ${moment.id}: unsupported Film Type ${key}.`);
  }
  const fmt = props.format, dims = FORMAT_DIMENSIONS[fmt], cfg = p.formats[fmt], l = p.layout;
  const authored = moment.presentation?.placement ?? "auto";
  const overlapping = props.shots.filter(s => s.startSeconds < moment.endSeconds && s.endSeconds > moment.startSeconds);
  const reviewed = overlapping.length > 0 && overlapping.every(s => Array.isArray(s.avoidRegions));
  // Film Type 2.9/2.10 keep the ONLY hard requirement: typography must stay
  // inside the platform safe area. Subject/region review stays available for
  // older pinned profiles, but these versions never demand it and never use
  // regions to reject, dim or move approved text. No detection is introduced.
  const enforceSubject = p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0";
  if ((authored === "auto" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0"))) && !reviewed && l.autoRequiresReviewedAvoidRegions) {
    throw new Error(`Moment ${moment.id}: Film Type auto placement needs reviewed, screen-space shot.avoidRegions (including camera motion for the entire dwell). Use [] only after reviewing a clear shot. Film Type 2.6 also requires review for explicit placement; supply regions for every overlapping shot.`);
  }
  const zones = authored !== "auto" ? [authored] : moment.presentation?.treatment === "inline-statement" || moment.kind === "statement"
    ? ["lower-right","mid-right","lower-left","mid-left","upper-right","upper-left"]
    : ["mid-left","upper-left","mid-right","upper-right","lower-left","lower-right"];
  const validZones = new Set(["upper-left","upper-right","mid-left","mid-right","lower-left","lower-right","center"]);
  if (zones.some(z => !validZones.has(z))) throw new Error(`Moment ${moment.id}: unsupported Film Type placement.`);
  const relevant = avoid.filter(r => r.startSeconds < moment.endSeconds && r.endSeconds > moment.startSeconds);
  const ranked = (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0"));
  const diffuse = (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0");
  const blocked: string[] = [];
  const candidates: {layout: FilmMomentLayout; score: number}[] = [];
  const ladder = moment.kind === "figure" && moment.segments.some(s => s.role === "hero" && splitQuantity(s.text))
    ? p.typography.figureLadderPx : moment.kind === "hook" ? p.typography.titleLadderPx : p.typography.statementLadderPx;
  const fractions = ranked ? [cfg.columnFraction, (cfg.columnFraction + cfg.wideColumnFraction)/2, cfg.wideColumnFraction] : [cfg.columnFraction,cfg.wideColumnFraction];
  for (const fraction of fractions) {
   for (const size of ranked ? ladder : [undefined]) {
    const padPx = safePadPx(p);
    const fitted = fitAtWidth(moment,p,fmt,Math.min(dims.width * fraction,dims.width * (1 - (cfg.safeArea.left??cfg.safeArea.side) - (cfg.safeArea.right??cfg.safeArea.side)) - 2*l.edgeInsetPx - 2*padPx),size);
    if (!fitted) continue;
    const w = fitted.widthPx / dims.width, h = fitted.heightPx / dims.height;
    const padX = padPx/dims.width, padY = padPx/dims.height;
    for (const zone of zones) {
      const x = zone === "center" ? ((cfg.safeArea.left??cfg.safeArea.side)+1-(cfg.safeArea.right??cfg.safeArea.side))/2 - w/2 : zone.endsWith("left") ? (cfg.safeArea.left??cfg.safeArea.side) + (l.edgeInsetPx+padPx)/dims.width : 1-(cfg.safeArea.right??cfg.safeArea.side)-(l.edgeInsetPx+padPx)/dims.width-w;
      const y = zone.startsWith("lower") ? 1-cfg.safeArea.bottom-(l.edgeInsetPx+padPx+l.motionClearancePx)/dims.height-h
        : clamp((zone.startsWith("upper") ? l.upperCentre : l.middleCentre) - h/2,cfg.safeArea.top+(l.edgeInsetPx+padPx)/dims.height,1-cfg.safeArea.bottom-(l.edgeInsetPx+padPx+l.motionClearancePx)/dims.height-h);
      const rect = {x,y,w,h};
      const moving = {...rect,h:rect.h + l.motionClearancePx/dims.height};
      const collision = expand(moving,l.collisionMarginPx/dims.width,l.collisionMarginPx/dims.height);
      if (!inSafe(moving,cfg.safeArea,padX,padY)) { if(blocked.length<3) blocked.push(`${zone}: outside safe area`); continue; }
      const obstacle = relevant.find(r => intersects(collision,r));
      if(obstacle && enforceSubject) { const detail=`${zone}: ink blocked by region ${avoid.indexOf(obstacle)} at ${obstacle.startSeconds}-${obstacle.endSeconds}s`; if(blocked.length<3&&!blocked.includes(detail)) blocked.push(detail); continue; }
      const strength = moment.presentation?.contrastStrength ?? p.contrast.defaultStrength;
      if (!Object.prototype.hasOwnProperty.call(p.contrast.strengths,strength)) throw new Error(`Moment ${moment.id}: unsupported contrastStrength.`);
      const contrastMode = moment.presentation?.contrastMode ?? "dark";
      if (contrastMode !== "dark" && contrastMode !== "light") throw new Error(`Moment ${moment.id}: unsupported contrastMode.`);
      // Match the painted superellipse including feather and entrance travel.
      // A smaller feather is allowed, never a smaller opaque core or weaker ink.
      let fieldFeatherPx: number | undefined;
      if (ranked && !diffuse) {
        const field = p.contrast.compactField!;
        const corner = Math.pow(2,1/field.exponent);
        const clearFeather = [field.featherPx, 64, 32].find(feather => {
          const ex = ((fitted.widthPx/2+field.paddingPx)*corner-fitted.widthPx/2+feather)/dims.width;
          const ey = ((fitted.heightPx/2+field.paddingPx)*corner-fitted.heightPx/2+feather)/dims.height;
          const envelope = expand(moving,ex,ey);
          return !relevant.some(region => intersects(envelope,region));
        });
        if(clearFeather === undefined) continue;
        fieldFeatherPx = clearFeather;
      }
      const layout: FilmMomentLayout = {...fitted,rect,placement:zone,subjectSafety:(reviewed && enforceSubject) ? "checked-against-supplied-regions" : "not-checked",contrastMode,strength};
      if (!ranked) return layout;
      if(diffuse) {
        const cfg=p.contrast.diffuseField!, radii=diffuseRadii(fitted.widthPx,fitted.heightPx,cfg);
        let peak=p.contrast.strengths[strength];
        // Maximum shadow opacity on a rectangle occurs nearest the field centre.
        // Include the whole entrance trajectory; never shorten feather to fit.
        const cx=(rect.x+w/2)*dims.width, cy=(rect.y+h/2)*dims.height;
        if(enforceSubject) for(const region of relevant){
          const dx=Math.max(region.x*dims.width-cx,0,cx-(region.x+region.w)*dims.width);
          const dy=Math.max(region.y*dims.height-(cy+l.motionClearancePx),0,cy-(region.y+region.h)*dims.height);
          const influence=diffuseAt(Math.hypot(dx/radii.rx,dy/radii.ry));
          if(influence>0) peak=Math.min(peak,cfg.maxSubjectAlpha/(influence+.001));
        }
        layout.fieldPeakAlpha=Math.floor(peak*1000)/1000;
      } else layout.fieldFeatherPx = fieldFeatherPx;
      // One authored phrase stays one phrase. Never rewrite roles, punctuation,
      // timing, ZWNJ, source text, or deliberate newlines to win a score.
      const hero = fitted.rows.filter(row => row.role === "hero");
      const lines = hero.length;
      const widths = hero.map(row => row.widthPx);
      const imbalance = widths.length > 1 ? 1 - Math.min(...widths)/Math.max(...widths) : 0;
      const shrink = 1 - (size ?? ladder[0])/ladder[0];
      const score = Math.max(0,lines-2)*8 + Math.max(0,lines-1)*.8
        + imbalance*2 + shrink*3 + h*2 + w*.25 + zones.indexOf(zone)*.04 + (diffuse && moment.kind === "hook" && zone.startsWith("lower") ? .2 : 0);
      candidates.push({layout,score});
    }
  }
   }
  if (candidates.length) {
    candidates.sort((a,b) => a.score-b.score);
    return candidates[0].layout;
  }
  throw new Error(`Moment ${moment.id}: no readable Film Type placement fits the safe area and supplied subject regions. Shorten the authored phrase, choose another legal placement, or change the shot; do not clip, hide text, or shrink below the profile floors. Diagnostics: ${blocked.join("; ") || "no size fits; check copy length and height"}`);
}

export function watermarkSafeArea(p: FilmProfile, format: PersianFormat) {
  const base = p.formats[format].safeArea;
  if (p.profileVersion !== "2.3.0" && p.profileVersion !== "2.4.0" && p.profileVersion !== "2.5.0" && p.profileVersion !== "2.6.0" && p.profileVersion !== "2.7.0" && p.profileVersion !== "2.8.0" && p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0") return {top:base.top,bottom:base.bottom,left:base.side,right:base.side};
  const safe = p.watermark.safeAreas?.[format];
  if (!safe || ![safe.top,safe.bottom,safe.left,safe.right].every(v => Number.isFinite(v) && v >= 0 && v < 1)
      || safe.top + safe.bottom >= 1 || safe.left + safe.right >= 1) {
    throw new Error("Film Type 2.3 requires explicit valid watermark safe areas.");
  }
  return safe;
}
function inWatermarkSafe(r: Rect, s: ReturnType<typeof watermarkSafeArea>): boolean {
  return r.x >= s.left - 1e-8 && r.y >= s.top - 1e-8
    && r.x + r.w <= 1-s.right+1e-8 && r.y + r.h <= 1-s.bottom+1e-8;
}

function measureLockup(props: PersianVideoProps, p: FilmProfile): FilmLockup | null {
  const mark = props.watermark ?? DEFAULT_WATERMARK, cfg = p.watermark;
  const parts = [
    {text:mark.persianText,size:cfg.persianFontPx,family:ESTEDAD_FAMILY,weight:500 as const,direction:"rtl" as const},
    {text:mark.latinText,size:cfg.latinFontPx,family:cfg.latinFontFamily,weight:cfg.latinWeight,direction:"ltr" as const},
  ].filter(v => v.text.length > 0);
  if (!parts.length) return null;
  let y = cfg.paddingPx, width = 0;
  const rows: FilmRow[] = [];
  for (const [index,part] of parts.entries()) {
    if (/\r|\n/.test(part.text)) throw new Error("Film Type brand lines cannot contain newlines; preserve the two explicit language lines.");
    if (index) y += cfg.lineGapPx;
    const ink = measureRun(part.text,part.size,part.weight,part.family,part.direction);
    rows.push({text:part.text,role:"brand",segmentIndex:index,fontSizePx:part.size,weight:part.weight,family:part.family,
      direction:part.direction,...ink,baselinePx:round(y+ink.abovePx),revealAfterSeconds:0,accentWords:[]});
    y += ink.abovePx + ink.belowPx; width = Math.max(width,ink.widthPx);
  }
  const result: FilmLockup = {rows,widthPx:Math.ceil(width+2*cfg.paddingPx),heightPx:Math.ceil(y+cfg.paddingPx),layout:"two-line",measured:true};
  const dims=FORMAT_DIMENSIONS[props.format],safe=watermarkSafeArea(p,props.format);
  if (result.widthPx > dims.width*(1-safe.left-safe.right)-2*p.layout.edgeInsetPx || result.heightPx > dims.height*(1-safe.top-safe.bottom)-2*p.layout.edgeInsetPx) {
    throw new Error("The complete Film Type bilingual watermark does not fit the safe area. Correct the brand input or author another lockup; clipping, ellipsis and unreadable shrinking are forbidden.");
  }
  return result;
}
function seededOffset(seed: string, n: number) {
  let value=2166136261;
  for (let i=0;i<seed.length;i++) value=Math.imul(value^seed.charCodeAt(i),16777619);
  return (value>>>0)%n;
}
function planWatermark(props: PersianVideoProps, p: FilmProfile, layouts: Record<string,FilmMomentLayout>, lockup: FilmLockup | null, avoid: TimedRect[]): NonNullable<PersianVideoProps["watermarkPlan"]> {
  if (!lockup) return [];
  const dims=FORMAT_DIMENSIONS[props.format],safe=watermarkSafeArea(p,props.format),l=p.layout,cfg=p.watermark;
  const repair=p.profileVersion === "2.3.0" || p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0")));
  // 2.9/2.10 plan the brand against real TEXT rectangles and the watermark safe
  // area only. Supplied subject regions never block or hide the brand.
  const subjectAvoid = (p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0") ? [] : avoid;
  const w=lockup.widthPx/dims.width,h=lockup.heightPx/dims.height;
  const padPx = safePadPx(p);
  const left=safe.left+(l.edgeInsetPx+padPx)/dims.width,right=1-safe.right-(l.edgeInsetPx+padPx)/dims.width-w;
  const top=safe.top+(l.edgeInsetPx+padPx)/dims.height,bottom=1-safe.bottom-(l.edgeInsetPx+padPx)/dims.height-h;
  const rects: Record<string,Rect> = {
    "lower-left":{x:left,y:bottom,w,h},"lower-right":{x:right,y:bottom,w,h},
    "mid-left":{x:left,y:.5-h/2,w,h},"mid-right":{x:right,y:.5-h/2,w,h},
    "upper-left":{x:left,y:top,w,h},"upper-right":{x:right,y:top,w,h},
  };
  const names=repair ? cfg.allowedZones : Object.keys(rects);
  if (!names?.length || names.some(z => !(z in rects) || (repair && p.profileVersion !== "2.8.0" && p.profileVersion !== "2.9.0" && p.profileVersion !== "2.10.0" && p.profileVersion !== "2.11.0" && z.startsWith("upper")))) {
    throw new Error("Film Type 2.3 watermark candidates must be explicit non-top zones.");
  }
  const offset=seededOffset(props.design!.seed,names.length);
  const order=[...names.slice(offset),...names.slice(0,offset)];
  if(cfg.preferNonTopPosition) order.sort((a,b)=>Number(a.startsWith("upper"))-Number(b.startsWith("upper")));
  if (repair && cfg.pairWithText) {
    // Prefer the side opposite the dominant AUTHORED text column, not an
    // arbitrary seeded relocation. Explicit text placements are never mirrored
    // inside the renderer; the review edit decisions own that creative choice.
    const sideTime={left:0,right:0};
    for (const m of props.moments) {
      const side=layouts[m.id].placement.endsWith("right") ? "right"
        : layouts[m.id].placement.endsWith("left") ? "left" : null;
      if (side) sideTime[side]+=m.endSeconds-m.startSeconds;
    }
    const preferred=sideTime.right >= sideTime.left ? "left" : "right";
    const rank=(zone:string)=>(zone.endsWith(preferred)?0:2)+(zone.startsWith("mid")?0:1);
    order.sort((a,b)=>rank(a)-rank(b));
  }
  const textRects: TimedRect[]=props.moments.map(m=>({...layouts[m.id].rect,h:layouts[m.id].rect.h+l.motionClearancePx/dims.height,startSeconds:m.startSeconds,endSeconds:m.endSeconds}));
  const obstacles=[...textRects,...subjectAvoid];
  const blockers:string[]=[];
  const clear=(r:Rect,start:number,end:number)=>{
    if(!inWatermarkSafe(r,safe))return false;
    const index=obstacles.findIndex(o=>o.startSeconds<end&&o.endSeconds>start&&intersects(expand(r,l.collisionMarginPx/dims.width,l.collisionMarginPx/dims.height),o));
    if(index<0)return true;
    const zone=Object.keys(rects).find(z=>rects[z]===r)??"unknown";
    const o=obstacles[index],label=index<textRects.length?`text ${props.moments[index].id}`:`subject region ${index-textRects.length}`;
    const detail=`${zone} ${start}-${end}s blocked by ${label} (${o.startSeconds}-${o.endSeconds}s)`;
    if(blockers.length<3&&!blockers.includes(detail))blockers.push(detail);
    return false;
  };
  if(p.profileVersion === "2.4.0" || (p.profileVersion === "2.5.0" || (p.profileVersion === "2.6.0" || (p.profileVersion === "2.7.0" || p.profileVersion === "2.8.0" || p.profileVersion === "2.9.0" || p.profileVersion === "2.10.0" || p.profileVersion === "2.11.0")))) return planMovingBrand(props.durationSeconds,
    props.shots.flatMap(s=>[s.startSeconds,s.endSeconds]),
    [...props.moments.flatMap(m=>[m.startSeconds,m.endSeconds]),...subjectAvoid.flatMap(r=>[r.startSeconds,r.endSeconds])],
    order,rects,clear,cfg,cfg.introDelaySeconds ?? 0,()=>blockers.join("; "));
  const maxCount=Math.max(1,Math.min(1+cfg.maxRelocations,Math.floor(props.durationSeconds/cfg.minDwellSeconds)));
  // Retry each schedule from scratch when reducing the count. Never expand a
  // previously safe dwell without revalidating its full new time interval.
  const counts=Array.from({length:maxCount},(_,i)=>repair && cfg.preferStablePosition ? i+1 : maxCount-i);
  // Try one position for the ENTIRE film first. Relocate only if no constant
  // position clears the full timeline; revalidate every candidate/dwell.
  for(const count of counts){
    const dwell=props.durationSeconds/count;
    const chosen: string[]=[];
    for(let index=0;index<count;index++){
      const zone=order.find(z=>!chosen.includes(z)&&clear(rects[z],index*dwell,(index+1)*dwell));
      if(!zone) break;
      chosen.push(zone);
    }
    if(chosen.length===count) return chosen.map((zone,index)=>({zone,startSeconds:index*dwell,endSeconds:(index+1)*dwell,rect:rects[zone],transition:index?"relocate-fade":"fade-in",reason:repair?"Full-dwell measured clearance; hard non-top safe area; stable opposite-side placement preferred":"Full-dwell measured ink clearance; single active lockup; non-top preferred"}));
  }
  throw new Error("No full-dwell safe slot exists for the complete Film Type watermark. Review placement/subject regions or explicitly author an empty watermark; do not silently hide the brand.");
}

/** Called in calculateMetadata, AND by the compose browser prepass. The frozen
 * result is written to the exact props sidecar before any production render. */
export async function prepareFilmTypeProps(props: PersianVideoProps): Promise<PersianVideoProps> {
  if (!isFilmType(props.design)) return props;
  await estedadReady;
  const profile=filmProfile(props.design!);
  const expectedHash = {
    "2.1.0":"c56aac71643bdeff4c27b75fa1ef1bb4e2997a3216a886d61dac78c3a021af0c",
    "2.2.0":"6d71bee9de74a627f393544bbcf9caf37b7349c422397b016f1f10597a1c43c2",
    "2.3.0":"3ee76f211682537b5b1ac457063a76cd81f1c84dd7fa916fddeef299ff3eecab",
    "2.4.0":"06a6cc6297df4146f9a8fa82af6617cec1e07ff420c72d134fbf878217dca543",
    "2.6.0":"1f763aed6dbfa2b61cdc6ce30558f6bc6e5ab318fb88e0125d84b07b0ae28967",
    "2.7.0":"b069a090061c1011d456cc5c63ff6989382f9044fdd38abb7c12db359710cea5",
    "2.8.0":"acfa082438f473f34f595a3a9132e03e26fda7dac0522f9c7ca00267272ac468",
    "2.9.0":"320a67a296d30cf1337b6c121cdd9367dfdc4e28fad1ba6af4f666e1e07551bf",
    "2.10.0":"60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0",
    "2.11.0":"ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687",
    "2.5.0":"ba44a26a97c680a8e714d5578fcab01cb7009a986e4d1361f9ce49dd3aab0261",
  }[profile.profileVersion];
  if(props.design!.contentHash!==expectedHash) throw new Error(`Unsupported Film Type ${profile.profileVersion} tokens; arbitrary snapshots cannot weaken layout or rollout guards.`);
  if(await sha256(profile)!==props.design!.contentHash) throw new Error("Film Type profile hash mismatch; re-resolve the design rather than silently changing a frozen snapshot.");
  await document.fonts.load(`${profile.watermark.latinWeight} ${profile.watermark.latinFontPx}px "${profile.watermark.latinFontFamily}"`, "Pathway");
  const input={format:props.format,durationSeconds:props.durationSeconds,design:props.design,shots:props.shots,
    moments:props.moments.map(m=>({id:m.id,kind:m.kind,startSeconds:m.startSeconds,endSeconds:m.endSeconds,segments:m.segments,presentation:m.presentation})),
    watermark:props.watermark??DEFAULT_WATERMARK};
  const inputHash=await sha256(input);
  if(!Number.isFinite(props.durationSeconds)||props.durationSeconds<=0) throw new Error("Film Type duration must be positive.");
  const avoid=timedAvoidRegions(props),layouts: Record<string,FilmMomentLayout>=Object.create(null),warnings:string[]=[];
  const contrastReviewMoments: string[]=[], unreviewedMoments: string[]=[];
  for(const moment of props.moments){
    if(typeof moment.id!=="string"||!moment.id.trim()) throw new Error("Film Type moment id must be a non-empty string.");
    if(moment.startSeconds<0||moment.endSeconds>props.durationSeconds) throw new Error(`Moment ${moment.id}: timing is outside the video.`);
    if(Object.prototype.hasOwnProperty.call(layouts,moment.id)) throw new Error(`Duplicate moment id ${moment.id}`);
    layouts[moment.id]=placeMoment(moment,props,profile,avoid);
    if((profile.profileVersion === "2.6.0" || (profile.profileVersion === "2.7.0" || profile.profileVersion === "2.8.0" || profile.profileVersion === "2.9.0" || profile.profileVersion === "2.10.0" || profile.profileVersion === "2.11.0"))) {
      const heroRows = layouts[moment.id].rows.filter(row => row.role === "hero");
      if(heroRows.length > 2) warnings.push(`${moment.id}: editorial-review-required: hero exceeds two lines; shorten or author timed beats against narration. Text/timing were preserved.`);
      if(moment.segments.some(s => s.role === "tail")) warnings.push(`${moment.id}: semantic-review-required: confirm the authored hero, not the tail, carries the intended emphasis. No automatic role swap.`);
      contrastReviewMoments.push(moment.id);
    }
    if((profile.profileVersion === "2.7.0" || profile.profileVersion === "2.8.0" || profile.profileVersion === "2.9.0" || profile.profileVersion === "2.10.0" || profile.profileVersion === "2.11.0") && moment.kind === "hook" && layouts[moment.id].placement.startsWith("lower")) warnings.push(`${moment.id}: hook-in-lower-third; review shot framing. Explicit placement remains binding.`);
    if(layouts[moment.id].subjectSafety==="not-checked") unreviewedMoments.push(moment.id);
  }
  // Aggregated once per film, not once per moment: same content, no repetition.
  if(contrastReviewMoments.length) warnings.push(`contrast-review-required: bounded field is not a measured footage-contrast guarantee; review all shots and transitions. (moments: ${contrastReviewMoments.join(", ")})`);
  if(unreviewedMoments.length) warnings.push(`explicit placement without reviewed avoid regions; subject collision is not-checked. (moments: ${unreviewedMoments.join(", ")})`);
  if((profile.profileVersion === "2.8.0" || profile.profileVersion === "2.9.0" || profile.profileVersion === "2.10.0" || profile.profileVersion === "2.11.0") && props.format === "vertical") warnings.push("Reels conservative safe area applied: top 14%, bottom 35%, left 8%, right 16%. Preview actual Instagram UI; expanded captions/comments are not guaranteed. Do not relax subject regions to fit.");
  if(profile.profileVersion === "2.9.0" || profile.profileVersion === "2.10.0" || profile.profileVersion === "2.11.0") warnings.push(`Film Type ${profile.profileVersion}: subject-region enforcement is OFF by default. Text and brand are kept inside the platform safe area only; overlap with people or objects in the footage is NOT evaluated and subjectSafety stays not-checked. Pin profileVersion 2.8.0 to restore reviewed-region enforcement.`);
  if(profile.profileVersion === "2.10.0" || profile.profileVersion === "2.11.0") warnings.push("Film Type 2.10: legibility comes from a small per-row field plus a two-layer glyph shadow. This is a readability aid, not a measured contrast guarantee; review bright footage yourself. Pin profileVersion 2.9.0 to restore the previous single-block field.");
  const lockup=measureLockup(props,profile);
  const filmType: FilmTypeLayout={version:profile.layoutVersion,inputHash,moments:layouts,lockup,warnings};
  const watermarkPlan=planWatermark(props,profile,layouts,lockup,avoid);
  if((profile.profileVersion === "2.4.0" || (profile.profileVersion === "2.5.0" || (profile.profileVersion === "2.6.0" || (profile.profileVersion === "2.7.0" || profile.profileVersion === "2.8.0" || profile.profileVersion === "2.9.0" || profile.profileVersion === "2.10.0" || profile.profileVersion === "2.11.0")))) && watermarkPlan.length &&
      !["left","right"].every(side=>watermarkPlan.some(slot=>slot.zone.endsWith(side))))
    warnings.push("Moving brand could not use both sides within supplied clearances; no crop/removal protection is guaranteed.");
  // A saved layout must still agree with the browser that actually paints it.
  // Do not silently revise a stale/differently measured props sidecar on render.
  if(props.filmType && (stableJSON(props.filmType)!==stableJSON(filmType) || stableJSON(props.watermarkPlan)!==stableJSON(watermarkPlan))) {
    throw new Error("Saved Film Type geometry is stale or differs from this browser's font measurement. Re-run persian_compose to create a fresh review snapshot.");
  }
  return {...props,filmType,watermarkPlan,watermarkPlanMeasured:true,
    watermarkMeasurement:lockup?{widthPx:lockup.widthPx,heightPx:lockup.heightPx,layout:"two-line" as const,measured:true as const}:undefined,
    moments:props.moments.map(m=>({...m,layoutGeometry:layouts[m.id].rect,stackHeightPx:layouts[m.id].heightPx,stackWidthPx:layouts[m.id].widthPx}))};
}
