/**
 * Persian text normalization, measurement, and line-break analysis.
 *
 * Browser-side twin of `lib/persian_text.py`. The two files implement the same
 * rules for the same reason: the Python side gates and reviews text before a
 * render, the TypeScript side lays it out during one, and if they disagree the
 * reviewer approves a layout the renderer will not produce.
 * `tests/contracts/test_persian_text_parity.py` runs a shared fixture corpus
 * through both and fails on any divergence, so this file is not free to drift.
 *
 * Read the Python module's docstring for why each rule exists. The comments
 * here cover only what is browser-specific.
 */

// ---------------------------------------------------------------------------
// Code points
// ---------------------------------------------------------------------------

export const ZWNJ = "\u200c";
export const ZWJ = "\u200d";
export const RLM = "\u200f";
export const LRM = "\u200e";

/** Format controls that are part of the text but paint nothing. */
export const INVISIBLE_FORMAT_CONTROLS = [ZWNJ, ZWJ, RLM, LRM] as const;

/** Letter-level spelling folds — see lib/persian_text.py LETTER_FOLDS. */
const LETTER_FOLDS: ReadonlyArray<readonly [string, string]> = [
  ["\u064a", "\u06cc"], // ARABIC YEH         → FARSI YEH
  ["\u0649", "\u06cc"], // ALEF MAKSURA       → FARSI YEH
  ["\u0643", "\u06a9"], // ARABIC KAF         → KEHEH
  ["\u06c0", "\u06d5"], // HEH WITH YEH ABOVE → AE
];

export const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

const SENTENCE_PUNCT = ".,!?؟،؛:…«»\"'()[]";

/**
 * Regex-escaped character class for the punctuation above.
 *
 * Built by escaping every character rather than hand-writing a class, because
 * a literal `]` or `-` inside a hand-written class silently changes its meaning
 * and would make punctuation stripping differ from Python's.
 */
const PUNCT_RE = new RegExp(
  "[" + SENTENCE_PUNCT.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&") + "]",
  "g",
);

const WS_RUN = /\s+/g;

// ---------------------------------------------------------------------------
// Normalization
// ---------------------------------------------------------------------------

/**
 * Fold Persian text to one canonical spelling. Preserves ZWNJ.
 *
 * `String.prototype.normalize("NFC")` matches Python's
 * `unicodedata.normalize("NFC", …)` — both implement UAX #15 — so the two
 * modules agree without either reimplementing composition.
 */
export function normalize(text: string): string {
  let out = text.normalize("NFC");
  for (const [src, dst] of LETTER_FOLDS) {
    out = out.split(src).join(dst);
  }
  return out;
}

/**
 * The string to MEASURE. Never render this.
 *
 * Estedad has no glyph for any invisible format control (verified against its
 * cmap; see public/fonts/estedad/README.md), so `measureText` may charge a
 * `.notdef` advance for each one. Measuring the painted string would therefore
 * report a width wider than what appears, and the fitter would shrink text that
 * already fits.
 */
export function measurableText(text: string): string {
  let out = normalize(text);
  for (const control of INVISIBLE_FORMAT_CONTROLS) {
    out = out.split(control).join("");
  }
  return out;
}

/**
 * Count of code points a reader perceives — excludes invisible controls,
 * collapsed whitespace, and combining marks. The unit for reading-speed budgets.
 *
 * Combining marks are detected with the `\p{M}` Unicode property, which is the
 * regex equivalent of Python's `unicodedata.combining(ch) != 0` for this
 * purpose: every character Python reports a non-zero combining class for is in
 * a Mark category. Iterates with a for-of loop so astral characters count once
 * rather than twice as surrogate halves.
 */
export function visibleLength(text: string): number {
  const collapsed = measurableText(text).replace(WS_RUN, " ").trim();
  let count = 0;
  for (const ch of collapsed) {
    if (!/\p{M}/u.test(ch)) count += 1;
  }
  return count;
}

/** Canonical form for comparing words (highlight matching, de-duplication). */
export function compareKey(word: string): string {
  return measurableText(word).replace(PUNCT_RE, "").trim().toLowerCase();
}

// ---------------------------------------------------------------------------
// Digits
// ---------------------------------------------------------------------------

/**
 * ASCII and Arabic-Indic digits → Persian-Indic. Only the ten digit glyphs are
 * substituted, so separators and signs keep their bidi class and the number
 * stays correctly placed inside an RTL run.
 */
export function toPersianDigits(text: string): string {
  return normalize(text).replace(/[0-9\u0660-\u0669]/g, (ch) => {
    const code = ch.codePointAt(0)!;
    const value = code <= 0x39 ? code - 0x30 : code - 0x0660;
    return PERSIAN_DIGITS[value];
  });
}

/** Persian-Indic digits → ASCII. For numbers that must be parsed, not read. */
export function toAsciiDigits(text: string): string {
  return normalize(text).replace(/[\u06f0-\u06f9]/g, (ch) =>
    String(ch.codePointAt(0)! - 0x06f0),
  );
}

// ---------------------------------------------------------------------------
// Line-break analysis
// ---------------------------------------------------------------------------

/** Bind forward — a line must never END on one. */
const PROCLITICS: ReadonlySet<string> = new Set([
  "به", "از", "با", "در", "بر", "برای", "تا", "بی", "هر", "یه", "یک",
  "این", "اون", "آن", "چه", "که", "و", "یا", "اگه", "اگر", "وقتی", "چون",
  "روی", "زیر", "بین", "مثل", "طبق", "بدون", "علیه",
]);

/** Bind backward — a line must never START on one. */
const ENCLITICS: ReadonlySet<string> = new Set([
  "رو", "را", "هم", "دیگه", "دیگر", "ام", "ات", "اش",
]);

/** Written ezafe: the word is bound to the next one, so never break after it. */
const EZAFE_ENDING = /(?:\u0650|\u0654|\u06c0|\u0647\u200c\u06cc|\u0647\u06cc)$/;

const LIGHT_VERB_MAX_VISIBLE_LEN = 6;
const LIGHT_VERB =
  /^(?:ن?می\u200c?|ب|ن)?(?:کن|ش|د|زن|گیر|خور|باش|کرد|شد)(?:م|ی|ه|یم|ید|ن|ند)$/;

const CHEAP_BREAK_AFTER_WORDS: ReadonlySet<string> = new Set([
  "اما", "ولی", "پس", "چون",
]);
const CHEAP_BREAK_AFTER_PUNCT = ["،", "؛", ".", "!", "؟", "…", ":"];

/**
 * How acceptable a break immediately AFTER a word is.
 *
 * Three-valued, not numeric: in a raggedness-minimizing breaker the objective
 * is a sum of squared slack in the thousands, so any "penalty" small enough to
 * be a preference is noise and any penalty large enough to matter is really a
 * constraint. Grammar is pruned from the search; style gets a bounded bonus.
 */
export type BreakClass = "forbidden" | "allowed" | "preferred";

export function isLightVerbConjugation(word: string): boolean {
  const stripped = measurableText(word);
  if (!stripped || [...stripped].length > LIGHT_VERB_MAX_VISIBLE_LEN) {
    return false;
  }
  return LIGHT_VERB.test(stripped);
}

export function endsWithExplicitEzafe(word: string): boolean {
  return EZAFE_ENDING.test(normalize(word).replace(/\s+$/, ""));
}

export function breakClass(word: string, nextWord: string | null): BreakClass {
  if (nextWord === null) return "allowed";

  const current = compareKey(word);
  if (PROCLITICS.has(current) || endsWithExplicitEzafe(word)) {
    return "forbidden";
  }

  const following = compareKey(nextWord);
  if (ENCLITICS.has(following) || isLightVerbConjugation(nextWord)) {
    return "forbidden";
  }

  const trimmed = normalize(word).replace(/\s+$/, "");
  if (CHEAP_BREAK_AFTER_PUNCT.some((p) => trimmed.endsWith(p))) {
    return "preferred";
  }
  if (CHEAP_BREAK_AFTER_WORDS.has(current)) return "preferred";

  return "allowed";
}

/**
 * Split a cue into words, preserving an explicit newline as its own token so an
 * authored break hint survives tokenization.
 */
export function splitWords(text: string): string[] {
  const tokens: string[] = [];
  const chunks = normalize(text).split("\n");
  chunks.forEach((chunk, index) => {
    for (const word of chunk.split(/\s+/)) {
      if (word) tokens.push(word);
    }
    if (index < chunks.length - 1) tokens.push("\n");
  });
  return tokens;
}
