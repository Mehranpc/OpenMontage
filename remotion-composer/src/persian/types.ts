/**
 * Shared prop contract for the Persian composition.
 *
 * This is the boundary between the Python pipeline and the renderer, so it is
 * written as plain JSON-serializable data with no derived or optional-magic
 * fields: everything the composition needs is either present or has an explicit
 * default here, never inferred from a sibling field. Cross-field inference is
 * what makes a props file that validates still render wrong.
 *
 * Times are in **seconds** at this boundary (what a transcript and an SRT speak),
 * and converted to frames exactly once, inside the components. Mixing units
 * across the boundary is the most common source of off-by-one-frame drift.
 *
 * ## The shape this replaced, and why the old one is gone rather than optional
 *
 * A moment used to be four independent slots: `kicker` above, `text` in the
 * middle, `unit` beside it, `label` below. Each slot had its own size and its own
 * colour, and the arrangement was chosen by the moment's `kind`. What reached the
 * screen for a study of 2264 people was a 260px accent numeral, the word «نفر»
 * floating at its baseline several hundred pixels to the left, and «دانشگاه
 * اولو، فنلاند» on a third line — three sizes, three left edges, and no sentence.
 * Nothing on screen said a *study* was being described, because no slot was for
 * saying it.
 *
 * The replacement is one field: `segments`, an ordered list. **The array order is
 * the paint order, top to bottom, and it is the reading order of one Persian
 * phrase.** So
 *
 *     [{ role: "lead", text: "مطالعهٔ دانشگاه اولوی فنلاند روی" },
 *      { role: "hero", text: "۲۲۶۴ نفر" }]
 *
 * paints «مطالعهٔ دانشگاه اولوی فنلاند روی» and, beneath it, «۲۲۶۴ نفر». The
 * grammar is stated by the author in the order Persian requires it, and the layout
 * obeys rather than inventing relationships. There is no sorting, no
 * role-priority table, and no "labels always go below" rule to fight: if the
 * phrase needs the quantity first and the qualifier after, the author writes them
 * in that order and that is what appears.
 *
 * The old slots are deleted rather than deprecated. Keeping them would keep the
 * arrangement they imply available, and a slot that exists gets filled — that is
 * how the floating «نفر» happened in the first place.
 */

import type { FilmTypeLayout, WatermarkDiagnostics } from "./filmType/layout";
import type { CameraMove } from "./motion";
import type { PersianFormat } from "./tokens";
import { compareKey, splitWords } from "./text";
import { validatePhraseLocks } from "./semanticPhraseLocks";

/**
 * What a moment is, editorially.
 *
 * This no longer decides the arrangement — `segments` does. It records what the
 * author judged the moment to *be*, which is what the audits reason about: a
 * figure's hero should be a quantity and not a sentence, a term's hero should be
 * a name that the phrase around it glosses, and a set that is nothing but
 * statements means the script's numbers and terms are not getting the frame.
 *
 * Kept as a declared field rather than inferred from the text because inference
 * would be wrong exactly where it matters: «۲۰۲۴» is a figure in one moment and a
 * date inside a source line in another, and only the author knows which.
 *
 * `hook` is the opening moment's kind, and it is declared for the same reason —
 * inferred "being the hook" silently cost the claim+qualifier style every
 * hook-scoped token. The predecessor inferred hook-ness from the flat display
 * shape (a `hero` carrying `accentWords` with no non-`source` sibling), so a hook
 * expressed as a claim plus a qualifier — a `hero` plus a `tail`, with no
 * `accentWords` anywhere — matched nothing and rendered at the ordinary size and
 * weight, an ordinary-looking first frame. A hook that must look like its
 * content to be recognised is not declared at all. The style inside a hook —
 * claim+qualifier or flat display — is derived from structure by
 * `isClaimQualifierHook` / `isFlatDisplayBlock` in `layout.ts`; the kind only
 * says this moment gets the hook's tokens.
 */
export type PersianMomentKind = "figure" | "term" | "statement" | "hook";

/**
 * The role a segment plays inside the phrase.
 *
 * Roles carry *emphasis and size*, never position — position is the array index.
 *
 * - `lead` — the part of the phrase that sets up the emphasis. Primary ink, at
 *   `LEAD_RATIO` of the hero size. Usually first, because Persian usually states
 *   the frame before the fact («مطالعهٔ … روی», «میانگین سنی شرکت‌کنندگان»).
 * - `hero` — the emphasised span. Accent colour, the largest type in the moment.
 *   Exactly one per moment: zero is a caption, two is no emphasis at all.
 * - `tail` — the part of the phrase that completes it *after* the emphasis. Same
 *   treatment as `lead`, except inside a claim+qualifier hook, where it takes the
 *   hook's size and weight — see `tailPxForMoment` / `weightForRole` in
 *   `layout.ts`. Exists because Persian word order sometimes puts the
 *   verb or the qualifier last («… را سه برابر می‌کند»), and forcing that into a
 *   `lead` would put it above the thing it follows.
 * - `source` — attribution. Smallest type, secondary ink, and it is not part of
 *   the phrase: it is a citation appended to it.
 */
export type PersianSegmentRole = "lead" | "hero" | "tail" | "source";
export type PersianSemanticPosterRole = "setup" | "bridge" | "subject_hero" | "connector" | "payoff";

/** One line-group of a moment's phrase. */
export interface PersianSegment {
  readonly role: PersianSegmentRole;
  /** Runtime-only semantic authorship for Film Type 2.16 editorial poster stacks. */
  readonly semanticRole?: PersianSemanticPosterRole;
  /** The Persian (or mixed) text of this segment. Painted exactly as given. */
  readonly text: string;
  /**
   * Inline accent words for the flat-hook treatment.
   *
   * Empty everywhere except a flat-hook moment: there the whole segment paints
   * at one size in primary ink and only these words carry the accent colour —
   * the emphasis expressed in colour rather than size. Matched by canonical
   * form, so trailing punctuation never defeats the match. A new segment-level
   * key, unrelated to the retired moment-level `highlightWords`, which stays
   * refused. The pipeline restricts this to moment-1 alone; the renderer paints
   * whatever it is given, because position in the timeline is not the
   * component's to know.
   */
  readonly accentWords?: readonly string[];
  /**
   * Multi-word semantic units that must remain intact on one rendered row.
   * These are layout constraints only: they never rewrite or replace `text`.
   * Obvious 3+-item comma lists also derive short multi-word locks at layout time.
   */
  readonly phraseLocks?: readonly string[];
  /**
   * Seconds after the moment's own start at which this segment arrives.
   *
   * Omitted or 0 means it arrives with the moment. A positive value builds the
   * moment in place: earlier segments stay on screen, this one joins them. That
   * is the mechanism for the case where two consecutive facts belong to one
   * thought and should accumulate rather than replace each other — a build is one
   * moment with two reveals, not two moments, which is why it is not subject to
   * the inter-moment gap floor.
   *
   * The reveal must leave enough time to read what it adds; `lib/persian_moments.py`
   * charges every step separately and refuses a build that outruns its own moment.
   */
  readonly revealAfterSeconds?: number;
}

/**
 * One typographic moment.
 *
 * `segments` is the whole content. There is no other text field, and there is no
 * field whose presence changes how another is painted.
 */
export type PersianV2Treatment = "editorial" | "inline-statement";
export type PersianV2Placement = "upper-left" | "upper-right" | "mid-left" | "mid-right" | "lower-left" | "lower-right" | "center" | "auto";
export type PersianV2Motion = "soft-reveal" | "cut-in";
export type PersianV2Emphasis = "none" | "inline";
export type PersianV2ContrastMode = "dark" | "light";
export type PersianEditorialRecipe = "editorial-hero-balanced" | "editorial-hero-compact" | "editorial-callout-balanced";
export type PersianPresentation = {
  readonly treatment?: PersianV2Treatment;
  readonly placement?: PersianV2Placement;
  readonly motion?: PersianV2Motion;
  readonly emphasis?: PersianV2Emphasis;
  readonly contrastMode?: PersianV2ContrastMode;
  readonly recipeId?: PersianEditorialRecipe;
  /** Film Type only; stable for the entire moment, not frame-adaptive. */
  readonly contrastStrength?: "soft" | "standard" | "strong";
};

export interface PersianMoment {
  readonly id: string;
  readonly kind: PersianMomentKind;
  /** Timeline position, seconds. */
  readonly startSeconds: number;
  readonly endSeconds: number;
  /** The phrase, in reading order, top to bottom. */
  readonly segments: readonly PersianSegment[];
  readonly purpose?: string;
  /** Explicit exception for a user-authored micro-hook; never set by auto-layout. */
  readonly userAuthoredShortHook?: boolean;
  readonly presentation?: PersianPresentation;
  /**
   * The narration words this moment is bound to.
   *
   * Recorded for provenance and for the sync audit, which checks that the moment
   * actually starts near where those words are spoken. It paints nothing.
   *
   * It exists because the shipped render drifted by up to 3.4 seconds against its
   * own narration: the timings had been rescaled from a *previous* video by the
   * duration ratio, which preserves the shape of the old edit and preserves
   * nothing about the new speech. A moment that names its anchor cannot be
   * rescaled into place — the audit re-derives its start from the transcript and
   * fails if the two disagree.
   */
  readonly anchorText?: string;
  /** Byte-exact display record. Strict copy is not normalized before props generation. */
  readonly exactText?: {
    readonly text: string;
    readonly sha256: string;
    readonly encoding: "utf-8";
    readonly normalization: "none";
  };
  /**
   * Fitted total ink+gap height in px at nominal width (`FittedMoment.heightPx`
   * in `layout.ts`). Attached by `persian_compose` when the node-canvas bridge
   * is available, so the verifier can scope ink measurement to the scrim
   * plateau instead of the whole zone envelope. Paints nothing; absent when the
   * bridge did not run.
   */
  readonly stackHeightPx?: number;
  /** Browser-fitted placement geometry, normalized to the nominal composition. */
  readonly layoutGeometry?: { x: number; y: number; w: number; h: number };
}

/**
 * One footage segment.
 *
 * `source` is a `staticFile()`-relative path, not an absolute URL: the render
 * must not depend on network availability, and a remote fetch mid-render produces
 * intermittent black frames that only appear under concurrency.
 */
export interface PersianShot {
  readonly id: string;
  /** Parent semantic narration beat; metadata only, never inferred from timing. */
  readonly semanticBeatId?: string;
  /** Shot-level visual event within the semantic beat. */
  readonly visualEventId?: string;
  readonly changeType?: "establish" | "action" | "reaction" | "detail" | "scale_change" | "punch_in";
  readonly narrativeRole?: "hook" | "exposition" | "conflict" | "turn" | "resolution";
  readonly humanPresence?: boolean;
  readonly showsSubject?: boolean;
  readonly semanticRole?: string;
  readonly semanticDirection?: string;
  readonly openingSemanticMatch?: boolean;
  readonly selectionReason?: string;
  /** Reviewed background readability class for adaptive editorial contrast. */
  readonly visualComplexity?: "simple" | "busy";
  /** Executable edit grammar. Persian currently renders hard cuts only. */
  readonly transitionIn?: "cut";
  /** Path relative to the composition's public dir. */
  readonly source: string;
  /** Timeline position, seconds. */
  readonly startSeconds: number;
  readonly endSeconds: number;
  /** In-point within the source clip, seconds. */
  readonly sourceInSeconds: number;
  readonly camera: CameraMove;
  /** Reviewed screen-space envelopes, including crop/camera motion. Times are absolute timeline seconds. */
  readonly avoidRegions?: readonly { x: number; y: number; w: number; h: number; startSeconds?: number; endSeconds?: number }[];
  /**
   * Attribution string for the credits beat. Required by both Pexels' and
   * Pixabay's licence terms, so it is not optional in the type — a shot that
   * cannot be attributed should not be in the manifest.
   */
  readonly attribution: string;
}

/**
 * A stretch of timeline with no footage behind it.
 *
 * Use only when no honest stock clip exists: never substitute a plate for
 * footage that is available and usable. The plate paints opaque
 * `voidBackground` (`#0B0B0C`, luma ~17/255), which reads as broken or
 * missing footage rather than design, so every plate must carry typography
 * across its whole window. Capped upstream so this cannot quietly become
 * the whole video.
 */
export interface PersianTypographicBeat {
  readonly id: string;
  readonly startSeconds: number;
  readonly endSeconds: number;
}


export type PersianCaptionMode = "sidecar_only" | "burned_captions" | "hybrid";

export interface PersianCaption {
  readonly id: string;
  /** Approved-script text; ASR wording is never allowed here. */
  readonly text: string;
  /** One or two pre-broken lines; the renderer never invents a third line. */
  readonly lines: readonly string[];
  readonly startSeconds: number;
  readonly endSeconds: number;
}

export interface PersianAudio {
  /** Narration path relative to the public dir, if any. */
  readonly narration?: string;
  /** Music bed path relative to the public dir, if any. */
  readonly music?: string;
  /** Music level when narration is absent. */
  readonly musicFlatVolume?: number;
  /** Music level when narration is present but not speaking. */
  readonly musicBaseVolume?: number;
  /** Music level while narration speaks. */
  readonly musicDuckVolume?: number;
  /** Derived speech windows from narration word timings; never authored copy. */
  readonly speechIntervals?: readonly {startSeconds: number; endSeconds: number}[];
  /**
   * Seconds of fade at the head and tail of the music bed.
   *
   * A bed that starts at full level on frame 0 and stops dead on the last frame
   * sounds like a mistake even when everything else is right, and it is the first
   * thing a viewer notices. Defaulted rather than optional-and-usually-absent.
   */
  readonly musicFadeSeconds?: number;
}

export interface PersianWatermark {
  /** Persian side of the lockup. Rendered in an explicit RTL span. */
  readonly persianText: string;
  /** Latin side of the lockup. Rendered in an explicit LTR span. */
  readonly latinText: string;
  readonly brandProfile?: "pathway-of-surrender-v1" | "authorized-override";
  readonly textHashes?: {
    readonly algorithm: "sha256-utf8";
    readonly persianText: string;
    readonly latinText: string;
  };
  readonly overrideAuthorization?: {
    readonly authorized: true;
    readonly source: "explicit_user_response";
    readonly decisionId: string;
    readonly reason: string;
    readonly recordedAt?: string;
  };
}

/**
 * Root props.
 *
 * Declared as a `type` alias rather than an `interface` deliberately: Remotion's
 * `CalculateMetadataFunction<T>` constrains `T` to `Record<string, unknown>`, and
 * TypeScript grants an implicit index signature to object-literal type aliases
 * but not to interfaces. The existing compositions in this repo
 * (`TitledVideoProps` and friends) use the same form for the same reason.
 */
export type PersianDesignSnapshot = {
  readonly version: 2;
  readonly profile: string;
  readonly seed: string;
  readonly profileVersion: string;
  readonly contentHash: string;
  readonly resolved: Record<string, unknown>;
};

export type PersianVideoProps = {
  readonly format: PersianFormat;
  readonly design?: PersianDesignSnapshot;
  /** Browser-measured, frozen Film Type layout; produced before render, not authored by hand. */
  readonly filmType?: FilmTypeLayout;
  readonly shots: readonly PersianShot[];
  readonly moments: readonly PersianMoment[];
  readonly typographicBeats?: readonly PersianTypographicBeat[];
  /** Delivery policy. Burned/hybrid captions are runtime-derived from approved copy. */
  readonly captionMode: PersianCaptionMode;
  readonly captions: readonly PersianCaption[];
  readonly audio?: PersianAudio;
  readonly watermark?: PersianWatermark;
  readonly watermarkPlan?: readonly { zone: string; startSeconds: number; endSeconds: number; rect: { x: number; y: number; w: number; h: number }; transition: string; reason?: string; }[];
  readonly watermarkPlanMeasured?: boolean;
  /** Structured planner evidence. Derived by browser preflight; never authored. */
  readonly watermarkDiagnostics?: WatermarkDiagnostics;
  readonly watermarkMeasurement?: { widthPx: number; heightPx: number; layout: "single-line" | "two-line"; measured: true };
  /** Total duration. Authoritative — `calculateMetadata` uses it directly. */
  readonly durationSeconds: number;
};

/** One canonical production brand. Missing input resolves to this exact record. */
export const CANONICAL_BRAND_PROFILE = "pathway-of-surrender-v1" as const;
export const DEFAULT_WATERMARK: PersianWatermark = {
  brandProfile: CANONICAL_BRAND_PROFILE,
  persianText: "طریقت تسلیم",
  latinText: "Pathway_of_Surrender",
  textHashes: {
    algorithm: "sha256-utf8",
    persianText: "2c2e0a9a76b57df83e04e712b82f6d51ec3af600b3a697b281f4d06d5331d02a",
    latinText: "aca253429dc44dff47a579cd23c532cb97df69771ad022c2236b66c55b1fd030",
  },
};

export const DEFAULT_AUDIO_LEVELS = {
  musicFlatVolume: 0.65,
  musicBaseVolume: 0.72,
  musicDuckVolume: 0.55,
  musicFadeSeconds: 1.5,
} as const;

/** Retired fields. Their presence in props is a hard error, not a warning. */
export const RETIRED_MOMENT_KEYS = [
  "text",
  "label",
  "kicker",
  "unit",
  "highlight",
  "highlightWords",
] as const;

/**
 * Group a moment's segments into reveal steps, in authored order.
 *
 * A step is everything that arrives at the same time. A moment with no
 * `revealAfterSeconds` anywhere is one step; a built moment is two or three.
 *
 * `source` is excluded: it is a citation appended to the phrase rather than part
 * of it, so it neither forms a step nor needs an emphasis of its own.
 */
export function momentRevealSteps(
  moment: PersianMoment,
): { readonly atSeconds: number; readonly segments: readonly PersianSegment[] }[] {
  const steps: { atSeconds: number; segments: PersianSegment[] }[] = [];
  for (const segment of moment.segments) {
    if (segment.role === "source") continue;
    const at = segment.revealAfterSeconds ?? 0;
    const existing = steps.find((step) => step.atSeconds === at);
    if (existing) existing.segments.push(segment);
    else steps.push({ atSeconds: at, segments: [segment] });
  }
  steps.sort((a, b) => a.atSeconds - b.atSeconds);
  return steps;
}

/**
 * Reject a malformed moment at render time, loudly.
 *
 * Remotion shallow-merges `--props` over `defaultProps`, so a moment that is
 * malformed in a way TypeScript cannot see at the boundary still reaches the
 * component. Every check below is one that produced a wrong-looking render that
 * nonetheless completed successfully.
 */
export function assertMomentIsWellFormed(moment: PersianMoment): void {
  const where = `Moment ${moment.id ?? "(no id)"}`;

  if (!Array.isArray(moment.segments) || moment.segments.length === 0) {
    throw new Error(
      `${where}: no segments. A moment is one Persian phrase carried by an ` +
        `ordered segment list; an empty list paints an empty scrim over the footage ` +
        `and the render still succeeds, which is why this throws.`,
    );
  }

  for (const key of RETIRED_MOMENT_KEYS) {
    if (key in (moment as unknown as Record<string, unknown>)) {
      throw new Error(
        `${where}: carries the retired key '${key}'. Slot-per-role moments ` +
          `(kicker above, hero, unit beside, label below) are gone: they produced ` +
          `three type sizes on three different left edges with no sentence anywhere. ` +
          `Express the phrase as ordered segments instead — the array order is the ` +
          `top-to-bottom reading order.`,
      );
    }
  }

  const heroes = moment.segments.filter((segment) => segment.role === "hero");
  if (heroes.length === 0) {
    throw new Error(
      `${where}: has no 'hero' segment. Nothing emphasised is a caption, not a ` +
        `moment — the whole phrase would paint at one size in one colour.`,
    );
  }

  // One hero *per reveal step*, not one per moment. A built moment is two or three
  // phrases arriving in turn, and each needs its own emphasis; what must never
  // happen is two heroes appearing together, because then neither is the emphasis.
  for (const step of momentRevealSteps(moment)) {
    const stepHeroes = step.segments.filter((segment) => segment.role === "hero");
    if (stepHeroes.length !== 1) {
      throw new Error(
        `${where}: the segments arriving at +${step.atSeconds}s contain ` +
          `${stepHeroes.length} 'hero' segments; exactly one is required. Zero means ` +
          `that step emphasises nothing; two means the emphasis competes with itself ` +
          `and reads as neither.`,
      );
    }
  }

  const sources = moment.segments.filter((segment) => segment.role === "source");
  if (sources.length > 1) {
    throw new Error(
      `${where}: has ${sources.length} 'source' segments; at most one is allowed.`,
    );
  }
  if (sources.length === 1 && moment.segments[moment.segments.length - 1].role !== "source") {
    throw new Error(
      `${where}: a 'source' segment must be last. It is a citation appended to ` +
        `the phrase, not a part of it, so anywhere else it interrupts the sentence.`,
    );
  }

  if (moment.exactText) {
    if (
      typeof moment.exactText.text !== "string" ||
      moment.exactText.text.split(/\s+/u).filter(Boolean).join(" ") !== moment.exactText.text
    ) {
      throw new Error(
        `${where}: strict copy must use one ASCII space between words and no ` +
          `leading, trailing, repeated, or line-break whitespace; unsupported ` +
          `whitespace is refused rather than repaired.`,
      );
    }
    const displayText = moment.segments
      .filter((segment) => segment.role !== "source")
      .map((segment) => segment.text)
      .join(" ");
    if (
      moment.exactText.encoding !== "utf-8" ||
      moment.exactText.normalization !== "none" ||
      displayText !== moment.exactText.text
    ) {
      throw new Error(
        `${where}: exactText does not equal the displayed segments byte-for-byte; ` +
          `strict punctuation, code points, whitespace, and digits may not be normalized.`,
      );
    }
  }

  for (const [index, segment] of moment.segments.entries()) {
    if (typeof segment.text !== "string" || segment.text.trim() === "") {
      throw new Error(
        `${where}: segment ${index} (${segment.role}) has no text. An empty ` +
          `segment reserves vertical space and paints nothing.`,
      );
    }
    validatePhraseLocks(
      segment.text,
      segment.phraseLocks,
      `${where}: segment ${index}`,
    );
    const reveal = segment.revealAfterSeconds ?? 0;
    if (!Number.isFinite(reveal) || reveal < 0) {
      throw new Error(
        `${where}: segment ${index} has revealAfterSeconds=${segment.revealAfterSeconds}; ` +
          `it must be a non-negative number of seconds after the moment's own start.`,
      );
    }
    // Flat-hook accent words: the renderer's half of the two-enforcer rule (the
    // pipeline audits the same in `lib/persian_moments.py`, seconds before any
    // clip is staged). Checked here because Remotion shallow-merges `--props`
    // over `defaultProps`, so a malformed accent list still reaches the paint.
    const accents = segment.accentWords ?? [];
    if (accents.length > 0 && segment.role !== "hero") {
      throw new Error(
        `${where}: segment ${index} carries accentWords on a ${segment.role} ` +
          `segment. Inline accent lives on the hero — the emphasis expressed in ` +
          `colour rather than size.`,
      );
    }
    if (accents.length > 3) {
      throw new Error(
        `${where}: segment ${index} lists ${accents.length} accent words; at ` +
          `most 3 are allowed. Several orange words are no emphasis at all.`,
      );
    }
    if (accents.length > 0) {
      const textWords = new Set(
        splitWords(segment.text)
          .filter((word) => word !== "\n")
          .map(compareKey),
      );
      for (const word of accents) {
        if (!textWords.has(compareKey(word))) {
          throw new Error(
            `${where}: segment ${index} accents ${JSON.stringify(word)}, which ` +
              `is not in its own text. An accent word that never paints is an ` +
              `emphasis nobody sees.`,
          );
        }
      }
    }
  }

  if (!Number.isFinite(moment.startSeconds) || !Number.isFinite(moment.endSeconds)) {
    throw new Error(
      `${where}: startSeconds/endSeconds must both be finite numbers, got ` +
        `${moment.startSeconds}/${moment.endSeconds}.`,
    );
  }
  if (moment.endSeconds <= moment.startSeconds) {
    throw new Error(
      `${where}: endSeconds (${moment.endSeconds}) must be after startSeconds ` +
        `(${moment.startSeconds}).`,
    );
  }

  const span = moment.endSeconds - moment.startSeconds;
  for (const [index, segment] of moment.segments.entries()) {
    const reveal = segment.revealAfterSeconds ?? 0;
    if (reveal >= span) {
      throw new Error(
        `${where}: segment ${index} reveals at +${reveal}s but the moment is only ` +
          `${span.toFixed(2)}s long, so it would never appear.`,
      );
    }
  }
}
