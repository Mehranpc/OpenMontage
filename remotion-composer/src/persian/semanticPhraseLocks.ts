import {compareKey, splitWords} from "./text";

export const MAX_PHRASE_LOCKS = 8;
const MAX_AUTO_LIST_ITEM_WORDS = 4;

function phraseKeys(text: string): string[] {
  return splitWords(text)
    .filter((word) => word !== "\n")
    .map(compareKey)
    .filter(Boolean);
}

function containsContiguousPhrase(text: string, phrase: string): boolean {
  const words = splitWords(text).map((word) =>
    word === "\n" ? "\n" : compareKey(word),
  );
  const wanted = phraseKeys(phrase);
  for (let start = 0; start + wanted.length <= words.length; start++) {
    if (words[start] === "\n") continue;
    let matches = true;
    for (let offset = 0; offset < wanted.length; offset++) {
      if (words[start + offset] === "\n" || words[start + offset] !== wanted[offset]) {
        matches = false;
        break;
      }
    }
    if (matches) return true;
  }
  return false;
}

/**
 * Validate explicit semantic units that must never be split across rendered rows.
 *
 * Phrase locks are layout metadata, not painted copy. They therefore compare by
 * canonical token form while the authored segment text itself remains untouched.
 */
export function validatePhraseLocks(
  text: string,
  rawPhraseLocks: unknown,
  where = "segment",
): string[] {
  if (rawPhraseLocks === undefined || rawPhraseLocks === null) return [];
  if (!Array.isArray(rawPhraseLocks)) {
    throw new Error(`${where}: phraseLocks must be a list of multi-word phrases.`);
  }
  if (rawPhraseLocks.length > MAX_PHRASE_LOCKS) {
    throw new Error(`${where}: phraseLocks may contain at most ${MAX_PHRASE_LOCKS} phrases.`);
  }

  const result: string[] = [];
  const seen = new Set<string>();
  for (const raw of rawPhraseLocks) {
    if (typeof raw !== "string" || raw.trim() === "" || /[\r\n]/u.test(raw)) {
      throw new Error(`${where}: phraseLocks entries must be non-empty single-line strings.`);
    }
    const phrase = raw.trim();
    const keys = phraseKeys(phrase);
    if (keys.length < 2) {
      throw new Error(`${where}: phraseLocks entries must contain at least two words.`);
    }
    if (!containsContiguousPhrase(text, phrase)) {
      throw new Error(
        `${where}: phraseLocks entry ${JSON.stringify(phrase)} is not a contiguous phrase in its segment text.`,
      );
    }
    const signature = keys.join("\u0000");
    if (seen.has(signature)) {
      throw new Error(`${where}: phraseLocks contains the same semantic phrase more than once.`);
    }
    seen.add(signature);
    result.push(phrase);
  }
  return result;
}

/**
 * Deterministic safety for explicit short lists: in a three-or-more-item comma
 * list, a 2–4 word item is already an obvious semantic unit. Keep that item
 * intact even when the editor did not need to spell out a phraseLocks field.
 *
 * Longer comma-delimited clauses are deliberately not inferred; use an explicit
 * phraseLocks entry when semantic grouping is not structurally obvious.
 */
export function deriveListPhraseLocks(text: string): string[] {
  const parts = text
    .split(/[،,]/u)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 3) return [];
  return parts.filter((part) => {
    const count = phraseKeys(part).length;
    return count >= 2 && count <= MAX_AUTO_LIST_ITEM_WORDS;
  });
}

export function effectivePhraseLocks(
  text: string,
  explicitPhraseLocks: unknown,
  where = "segment",
): string[] {
  const explicit = validatePhraseLocks(text, explicitPhraseLocks, where);
  const derived = deriveListPhraseLocks(text);
  const result: string[] = [];
  const seen = new Set<string>();
  for (const phrase of [...explicit, ...derived]) {
    const signature = phraseKeys(phrase).join("\u0000");
    if (!seen.has(signature)) {
      seen.add(signature);
      result.push(phrase);
    }
  }
  return result;
}

/** Return word indexes after which a line break would split a protected phrase. */
export function lockedBreakBoundaries(
  text: string,
  words: readonly string[],
  explicitPhraseLocks: unknown,
  where = "segment",
): Set<number> {
  const locks = effectivePhraseLocks(text, explicitPhraseLocks, where);
  const indexed = words
    .map((word, index) =>
      word === "\n" ? null : {index, key: compareKey(word)},
    )
    .filter((entry): entry is {index: number; key: string} => entry !== null);
  const forbidden = new Set<number>();

  for (const phrase of locks) {
    const wanted = phraseKeys(phrase);
    for (let start = 0; start + wanted.length <= indexed.length; start++) {
      let matches = true;
      for (let offset = 0; offset < wanted.length; offset++) {
        const entry = indexed[start + offset];
        if (
          entry.index !== indexed[start].index + offset ||
          entry.key !== wanted[offset]
        ) {
          matches = false;
          break;
        }
      }
      if (!matches) continue;
      for (let offset = 0; offset < wanted.length - 1; offset++) {
        forbidden.add(indexed[start + offset].index);
      }
    }
  }
  return forbidden;
}
