/**
 * #387 v3 opening hook = Mehran's approved design (`Hook_v2_photo.html`).
 *
 * The owner approved that HTML/CSS exactly, with these changes only: the hero face is
 * Kahroba (not Lalezar), the hero size is 140px (not 150px), and the soft shade behind
 * the text spans the full frame width (left/right -110px, not -55px; owner review of the
 * acceptance-3 render, which showed a 55px gap on each side). The CSS below is that
 * file's CSS, class names prefixed, nothing else changed. It is painted as real DOM so
 * Chrome lays it out exactly like the approved preview (frosted pill, CSS brush, shade,
 * full-frame treatment). No animation: the composition is complete on its first frame.
 *
 * Layout and paint share one element tree (`hookTree`). The prepass mounts that tree in
 * the same browser, reads every line box, and freezes the line breaks, so paint never
 * re-wraps differently from what was measured and verified.
 */
import React from "react";
import { AbsoluteFill } from "remotion";
import { KAHROBA_FAMILY, VAZIRMATN_FAMILY } from "../fonts";

export const DESIGNED_HOOK_VERSION = "mehran-hook-v2-photo" as const;
export const DESIGNED_HOOK_QUESTION_PX = 68;
export const DESIGNED_HOOK_HERO_PX = 140;
/** Stage and hook box from the design, in 1080x1920 pixels. */
export const DESIGNED_HOOK_BOX = {left: 110, right: 110, top: 455, stageWidth: 1080, stageHeight: 1920} as const;

export type DesignedHook = {
  version: typeof DESIGNED_HOOK_VERSION;
  questionLines: string[];
  questionFontPx: number;
  bridge?: string;
  heroLines: string[];
  heroFontPx: number;
};

/** The approved CSS (Hook_v2_photo.html), prefixed `omh-`. Only the hero font family
 * (Kahroba) and size (140px, overridable per line fit) and the full-width shade differ,
 * as approved. */
export const DESIGNED_HOOK_CSS = `
.omh-stage{position:absolute;inset:0;width:1080px;height:1920px;overflow:hidden;
  font-family:'${VAZIRMATN_FAMILY}',sans-serif;font-size:16px;line-height:normal;font-weight:400;
  letter-spacing:normal;direction:rtl;text-align:start;font-synthesis:none;font-kerning:normal}
.omh-stage *{margin:0;padding:0;box-sizing:border-box}
.omh-treatment{position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(to bottom,rgba(0,0,0,.05) 0%,rgba(0,0,0,.10) 24%,rgba(0,0,0,.24) 44%,rgba(0,0,0,.32) 62%,rgba(0,0,0,.22) 78%,rgba(0,0,0,.08) 100%)}
.omh-wrap{position:absolute;left:110px;right:110px;top:455px;text-align:center;z-index:3;isolation:isolate}
.omh-wrap::before{content:"";position:absolute;z-index:-2;left:-110px;right:-110px;top:-105px;bottom:-135px;
  background:radial-gradient(ellipse at 50% 46%,rgba(0,0,0,.60) 0%,rgba(0,0,0,.48) 34%,rgba(0,0,0,.22) 66%,rgba(0,0,0,0) 88%);
  filter:blur(2px)}
.omh-accent{width:100px;height:5px;margin:0 auto 38px;border-radius:999px;
  background:linear-gradient(90deg,#FFB800,#FFE176);box-shadow:0 0 18px rgba(255,184,0,.20)}
.omh-question{max-width:860px;margin:0 auto;color:#F8F8F8;font-size:68px;line-height:1.52;font-weight:800;
  letter-spacing:-1.4px;text-shadow:0 4px 18px rgba(0,0,0,.82),0 1px 2px rgba(0,0,0,.95);text-wrap:balance}
.omh-question .omh-highlight{color:#FFCF33;font-weight:900;text-shadow:0 4px 18px rgba(0,0,0,.76),0 0 20px rgba(255,195,48,.08)}
.omh-bridge{display:inline-flex;align-items:center;justify-content:center;margin-top:44px;padding:18px 48px 20px;
  min-height:78px;border-radius:999px;color:#F4F4F4;font-size:37px;line-height:1.2;font-weight:600;
  background:linear-gradient(180deg,rgba(42,39,37,.64),rgba(26,24,23,.50));border:1.5px solid rgba(255,255,255,.18);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 12px 38px rgba(0,0,0,.28);
  -webkit-backdrop-filter:blur(16px) saturate(110%);backdrop-filter:blur(16px) saturate(110%)}
.omh-hero-wrap{position:relative;display:inline-block;margin-top:35px;padding:0 18px 30px}
.omh-hero{font-family:'${KAHROBA_FAMILY}','${VAZIRMATN_FAMILY}',sans-serif;color:#FFCF33;font-size:140px;line-height:1.03;
  font-weight:800;letter-spacing:-1px;text-shadow:0 6px 22px rgba(0,0,0,.72),0 14px 34px rgba(0,0,0,.42)}
.omh-brush{position:absolute;left:5%;right:5%;bottom:4px;height:28px;transform:rotate(-2.2deg);opacity:.98}
.omh-brush::before,.omh-brush::after{content:"";position:absolute;inset:0;background:#FFCF33;
  border-radius:80% 22% 72% 24% / 65% 42% 58% 34%}
.omh-brush::before{clip-path:polygon(0 55%,7% 34%,18% 29%,31% 20%,48% 23%,64% 16%,82% 22%,100% 13%,97% 51%,82% 62%,66% 55%,48% 66%,28% 56%,12% 72%,0 70%)}
.omh-brush::after{opacity:.45;transform:translateY(6px) scaleX(.96);filter:blur(.7px)}
.omh-line{white-space:nowrap}
.omh-base{display:inline-block;width:0;height:0}
.omh-stage.omh-hidden-glyphs .omh-question,.omh-stage.omh-hidden-glyphs .omh-question *,
.omh-stage.omh-hidden-glyphs .omh-bridge,.omh-stage.omh-hidden-glyphs .omh-hero{color:transparent;text-shadow:none}
`;

/** One element tree for both the prepass (DOM) and paint (React). */
export type HookNode = {tag: "div" | "section" | "span" | "br"; cls?: string; text?: string; style?: Record<string, string>; children?: HookNode[]; role?: string};

const line = (text: string, role: string, marker: boolean): HookNode =>
  ({tag: "span", cls: "omh-line", role, children: [...(marker ? [{tag: "span", cls: "omh-base"} as HookNode] : []), {tag: "span", text}]});
const withBreaks = (nodes: HookNode[]): HookNode[] => nodes.flatMap((node, i) => i ? [{tag: "br"} as HookNode, node] : [node]);

/** `marker` adds zero-size baseline probes; they never change line boxes. */
export function hookTree(hook: Pick<DesignedHook, "questionLines" | "questionFontPx" | "bridge" | "heroLines" | "heroFontPx">, marker = false): HookNode[] {
  const wrap: HookNode[] = [{tag: "div", cls: "omh-accent"}];
  if (hook.questionLines.length) wrap.push({tag: "div", cls: "omh-question", role: "question",
    style: hook.questionFontPx !== DESIGNED_HOOK_QUESTION_PX ? {fontSize: `${hook.questionFontPx}px`} : undefined,
    children: withBreaks(hook.questionLines.map(text => line(text, "question-line", marker)))});
  if (hook.bridge) wrap.push({tag: "div", cls: "omh-bridge", role: "bridge", children: [line(hook.bridge, "bridge-line", marker)]}, {tag: "br"});
  wrap.push({tag: "div", cls: "omh-hero-wrap", role: "hero-wrap", children: [
    {tag: "div", cls: "omh-hero", role: "hero",
      style: hook.heroFontPx !== DESIGNED_HOOK_HERO_PX ? {fontSize: `${hook.heroFontPx}px`} : undefined,
      children: withBreaks(hook.heroLines.map(text => line(text, "hero-line", marker)))},
    {tag: "div", cls: "omh-brush"},
  ]});
  return [{tag: "div", cls: "omh-treatment"}, {tag: "section", cls: "omh-wrap", role: "wrap", children: wrap}];
}

export function hookTreeToDom(nodes: HookNode[], doc: Document): Node[] {
  return nodes.map(node => {
    if (node.tag === "br") return doc.createElement("br");
    const el = doc.createElement(node.tag);
    if (node.cls) el.className = node.cls;
    if (node.role) el.dataset.omhRole = node.role;
    if (node.style) Object.assign(el.style, node.style);
    if (node.text !== undefined) el.textContent = node.text;
    for (const child of hookTreeToDom(node.children ?? [], doc)) el.appendChild(child);
    return el;
  });
}

function toReact(nodes: HookNode[]): React.ReactNode[] {
  return nodes.map((node, i) => node.tag === "br" ? <br key={i}/> : React.createElement(node.tag,
    {key: i, className: node.cls, "data-omh-role": node.role, style: node.style}, node.text ?? toReact(node.children ?? [])));
}

export const DesignedHookPaint: React.FC<{momentId: string; hook: DesignedHook; hideGlyphs: boolean}> = ({momentId, hook, hideGlyphs}) =>
  <AbsoluteFill data-film-type-moment={momentId} data-film-type-placement="upper-center" data-film-designed-hook={hook.version} style={{pointerEvents: "none"}}>
    <style>{DESIGNED_HOOK_CSS}</style>
    <div className={`omh-stage${hideGlyphs ? " omh-hidden-glyphs" : ""}`} aria-hidden={hideGlyphs || undefined}>{toReact(hookTree(hook))}</div>
  </AbsoluteFill>;

/* ------------------------------------------------------------------ prepass */

export type DesignedHookSegments = {question?: {text: string; index: number}; bridge?: {text: string; index: number}; hero: {text: string; index: number}};
export type DesignedHookRow = {
  text: string; role: string; segmentIndex: number; fontSizePx: number; weight: 600 | 800 | 900;
  family: string; direction: "rtl"; abovePx: number; belowPx: number; widthPx: number; baselinePx: number;
  revealAfterSeconds: number; accentWords: readonly string[];
};
export type DesignedHookMeasure = {hook: DesignedHook; rows: DesignedHookRow[]; widthPx: number; heightPx: number};

const r2 = (v: number) => Math.round(v * 100) / 100;
let host: HTMLDivElement | null = null;
function measureHost(): HTMLDivElement {
  if (host && host.isConnected) return host;
  const style = document.createElement("style");
  style.textContent = DESIGNED_HOOK_CSS;
  document.head.appendChild(style);
  host = document.createElement("div");
  host.setAttribute("aria-hidden", "true");
  Object.assign(host.style, {position: "fixed", left: "-20000px", top: "0px", width: "1080px", height: "1920px", visibility: "hidden", pointerEvents: "none"});
  document.body.appendChild(host);
  return host;
}
function mount(nodes: HookNode[]): HTMLElement {
  const h = measureHost();
  h.replaceChildren();
  const stage = document.createElement("div");
  stage.className = "omh-stage";
  for (const node of hookTreeToDom(nodes, document)) stage.appendChild(node);
  h.appendChild(stage);
  return stage;
}

/** Let Chrome balance the words exactly like `text-wrap: balance` in the design,
 * then read which words share a line. Words are whole runs (ZWNJ stays inside). */
function balancedLines(text: string, cls: "omh-question" | "omh-hero", fontPx: number): string[] {
  const words = text.split(/\s+/u).filter(Boolean);
  const box: HookNode = {tag: "div", cls, style: {fontSize: `${fontPx}px`, ...(cls === "omh-hero" ? {textWrap: "balance", maxWidth: `${860 - 36}px`} : {})},
    children: words.flatMap((word, i) => [...(i ? [{tag: "span", text: " "} as HookNode] : []), {tag: "span", cls: "omh-word", text: word} as HookNode])};
  const stage = mount([{tag: "section", cls: "omh-wrap", children: [box]}]);
  const spans = [...stage.querySelectorAll<HTMLElement>(".omh-word")];
  const lines: string[][] = [];
  let lastTop = Number.NEGATIVE_INFINITY;
  for (const span of spans) {
    const top = span.getBoundingClientRect().top;
    if (Math.abs(top - lastTop) > fontPx * .5) { lines.push([]); lastTop = top; }
    lines[lines.length - 1].push(span.textContent ?? "");
  }
  return lines.map(words => words.join(" "));
}

function lineWidth(nodes: HookNode[], role: string): number {
  const stage = mount(nodes);
  return Math.max(...[...stage.querySelectorAll<HTMLElement>(`[data-omh-role="${role}"]`)].map(el => el.getBoundingClientRect().width));
}

let inkCanvas: CanvasRenderingContext2D | null = null;
function ink(text: string, font: string): {abovePx: number; belowPx: number} {
  if (!inkCanvas) inkCanvas = document.createElement("canvas").getContext("2d");
  if (!inkCanvas) throw new Error("Designed hook requires a real browser canvas.");
  inkCanvas.font = font;
  inkCanvas.direction = "rtl";
  inkCanvas.textBaseline = "alphabetic";
  const m = inkCanvas.measureText(text);
  if (![m.actualBoundingBoxAscent, m.actualBoundingBoxDescent].every(Number.isFinite)) throw new Error("Browser did not return glyph bounds for the designed hook.");
  return {abovePx: r2(Math.max(0, m.actualBoundingBoxAscent)), belowPx: r2(Math.max(0, m.actualBoundingBoxDescent))};
}

/** Question: the design's 68px; only if it would need more than three lines does it
 * step down (2px, floor 50px). Hero: the approved 140px on one line; only a line wider
 * than the hero box steps down (2px, floor 112px), then balances onto two lines.
 * The bridge pill stays one line at its design size; a pill wider than the hook box
 * returns null so the caller keeps the previous staged path rather than overflow. */
export function measureDesignedHook(segments: DesignedHookSegments): DesignedHookMeasure | null {
  let questionFontPx = DESIGNED_HOOK_QUESTION_PX, questionLines: string[] = [];
  if (segments.question) {
    questionLines = balancedLines(segments.question.text, "omh-question", questionFontPx);
    while (questionLines.length > 3 && questionFontPx > 50) {
      questionFontPx -= 2;
      questionLines = balancedLines(segments.question.text, "omh-question", questionFontPx);
    }
    if (questionLines.length > 3) return null;
  }
  const heroBox = 860 - 36;
  let heroFontPx = DESIGNED_HOOK_HERO_PX, heroLines = [segments.hero.text];
  const heroWidth = (px: number, lines: string[]) => lineWidth(hookTree({questionLines: [], questionFontPx, heroLines: lines, heroFontPx: px}), "hero-line");
  while (heroWidth(heroFontPx, heroLines) > heroBox + .5 && heroFontPx > 112) heroFontPx -= 2;
  if (heroWidth(heroFontPx, heroLines) > heroBox + .5) {
    heroLines = balancedLines(segments.hero.text, "omh-hero", heroFontPx);
    if (heroLines.length > 2 || heroWidth(heroFontPx, heroLines) > heroBox + .5) return null;
  }
  const hook: DesignedHook = {version: DESIGNED_HOOK_VERSION, questionLines, questionFontPx, heroLines, heroFontPx,
    ...(segments.bridge ? {bridge: segments.bridge.text} : {})};
  const stage = mount(hookTree(hook, true));
  const wrap = stage.querySelector<HTMLElement>('[data-omh-role="wrap"]')!.getBoundingClientRect();
  if (segments.bridge) {
    // The pill's own content box: 860px minus its 48px side padding and 1.5px borders.
    const text = stage.querySelector<HTMLElement>('[data-omh-role="bridge-line"]')!.getBoundingClientRect();
    if (text.width > 860 - 2 * 48 - 3 + .5) return null;
  }
  const rows: DesignedHookRow[] = [];
  const read = (role: string, segment: {index: number}, rowRole: string, fontPx: number, weight: 600 | 800 | 900, family: string, canvasFont: string) => {
    for (const el of stage.querySelectorAll<HTMLElement>(`[data-omh-role="${role}"]`)) {
      const text = el.textContent ?? "";
      const base = el.querySelector<HTMLElement>(".omh-base")!.getBoundingClientRect().top;
      rows.push({text, role: rowRole, segmentIndex: segment.index, fontSizePx: fontPx, weight, family, direction: "rtl",
        ...ink(text, canvasFont), widthPx: r2(el.getBoundingClientRect().width), baselinePx: r2(base - wrap.top),
        revealAfterSeconds: 0, accentWords: []});
    }
  };
  if (segments.question) read("question-line", segments.question, "lead", questionFontPx, 800, VAZIRMATN_FAMILY, `800 ${questionFontPx}px "${VAZIRMATN_FAMILY}"`);
  if (segments.bridge) read("bridge-line", segments.bridge, "lead", 37, 600, VAZIRMATN_FAMILY, `600 37px "${VAZIRMATN_FAMILY}"`);
  read("hero-line", segments.hero, "hero", heroFontPx, 900, KAHROBA_FAMILY, `800 ${heroFontPx}px "${KAHROBA_FAMILY}"`);
  host?.replaceChildren();
  return {hook, rows, widthPx: 860, heightPx: Math.ceil(wrap.height)};
}
