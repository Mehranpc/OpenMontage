"""Persian (Farsi) text normalization, measurement, and line-break analysis.

The single Python-side source of truth for how this repo treats Persian text.
Its sibling is `remotion-composer/src/persian/text.ts`, which reimplements the
same rules for the browser; `tests/contracts/test_persian_text_parity.py` pins
the two to identical behaviour on a shared fixture corpus so a change to one
cannot silently diverge from the other.

Four problems are solved here, in the order they bite a Persian subtitle:

1. **Normalization.** Persian is written with Arabic-block code points, and the
   same visual letter has several encodings. Arabic yeh U+064A and Farsi yeh
   U+06CC both look like «ی»; Arabic kaf U+0643 and keheh U+06A9 both look like
   «ک». Text arriving from a transcript, a web article, or a user's keyboard
   mixes them freely. Unless they are folded to one spelling, `"کی" != "كی"`,
   highlight matching misses, and search de-duplication fails.

2. **Measurement vs painting.** ZWNJ (U+200C) is semantically part of a Persian
   word — «می‌روم» is one word — but it has no glyph in Estedad (see
   `assets/fonts/estedad/README.md`). Measuring a string containing it can
   charge a `.notdef` advance, so measurement and painting must use different
   strings: `measurable_text()` for width math, the original for display.

3. **Digits.** Persian content wants Persian-Indic digits (۰-۹, U+06F0-U+06F9),
   but numbers arrive as ASCII. Arabic-Indic digits (U+0660-U+0669) also show up
   in text copied from Arabic sources and must fold to the Persian forms, since
   Estedad draws them differently.

4. **Line breaking.** Persian binds words grammatically in ways that make some
   break positions read as errors to a native reader. Those are enumerated as
   *constraints* in `break_class()`, not as soft costs — see the note there.

Nothing in this module touches timing, and nothing here is renderer-specific.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Code points that carry meaning in the rules below.
# ---------------------------------------------------------------------------

ZWNJ = "\u200c"  # zero-width non-joiner — «می‌روم» is ONE word
ZWJ = "\u200d"  # zero-width joiner
RLM = "\u200f"  # right-to-left mark
LRM = "\u200e"  # left-to-right mark

#: Format controls that are semantically part of the text but paint nothing.
#: Stripped for measurement, never stripped for display.
INVISIBLE_FORMAT_CONTROLS = frozenset({ZWNJ, ZWJ, RLM, LRM})

#: Letter-level spelling folds. Both directions of each pair render as the same
#: Persian letter, so the encoding difference is noise that breaks equality.
LETTER_FOLDS = {
    "\u064a": "\u06cc",  # ARABIC YEH        → FARSI YEH        ي → ی
    "\u0649": "\u06cc",  # ALEF MAKSURA      → FARSI YEH        ى → ی
    "\u0643": "\u06a9",  # ARABIC KAF        → KEHEH            ك → ک
    "\u06c0": "\u06d5",  # HEH WITH YEH ABOVE→ AE               ۀ → ە  (see note)
}

#: Digit folds. Keys are ASCII and Arabic-Indic; values are Persian-Indic.
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ASCII_TO_PERSIAN = {str(i): PERSIAN_DIGITS[i] for i in range(10)}
_ARABIC_INDIC_TO_PERSIAN = {chr(0x0660 + i): PERSIAN_DIGITS[i] for i in range(10)}
_PERSIAN_TO_ASCII = {PERSIAN_DIGITS[i]: str(i) for i in range(10)}

#: Sentence-level punctuation stripped when comparing words for highlighting.
#: Grammatical marks (the ezafe kasra U+0650, hamza above U+0654, U+06C0) are
#: deliberately NOT in this set — `break_class` needs them to detect a bound
#: word, and stripping them would erase the very signal it reads.
SENTENCE_PUNCT = frozenset(".,!?؟،؛:؛…«»\"'()[]")

_WS_RUN = re.compile(r"\s+")
_PUNCT_RE = re.compile("[" + re.escape("".join(sorted(SENTENCE_PUNCT))) + "]")


# ---------------------------------------------------------------------------
# 1. Normalization
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Fold Persian text to one canonical spelling.

    NFC first (so a decomposed sequence and its composed form agree), then the
    letter folds. Order matters: NFC can produce an Arabic yeh from a
    decomposed sequence, which the fold then converts to a Farsi yeh.

    ZWNJ is PRESERVED — it is part of the word, not noise. Callers that need a
    measurable string want `measurable_text()`; callers comparing words want
    `compare_key()`.

    Raises:
        TypeError: if `text` is not a str. Silently coercing would let a None
            from a malformed transcript become the string "None" and ship.
    """
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")
    folded = unicodedata.normalize("NFC", text)
    for src, dst in LETTER_FOLDS.items():
        folded = folded.replace(src, dst)
    return folded


def measurable_text(text: str) -> str:
    """The string to measure — normalized, with invisible controls removed.

    Never render this. It differs from what is painted precisely because the
    removed code points paint nothing but can still be charged an advance width
    when the font has no glyph for them (Estedad has none for any of them).
    """
    out = normalize(text)
    for control in INVISIBLE_FORMAT_CONTROLS:
        out = out.replace(control, "")
    return out


def visible_length(text: str) -> int:
    """Count of code points a reader actually perceives.

    Excludes invisible format controls, whitespace runs beyond one space, and
    combining marks (a kasra over a letter adds no reading time). This is the
    unit for reading-speed budgets, not `len()`.
    """
    collapsed = _WS_RUN.sub(" ", measurable_text(text)).strip()
    return sum(1 for ch in collapsed if unicodedata.combining(ch) == 0)


def compare_key(word: str) -> str:
    """Canonical form for comparing two words.

    Normalized, invisible controls dropped, sentence punctuation dropped,
    lowercased for any embedded Latin. Grammatical marks survive, so «واکنشِ»
    and «واکنش» remain distinguishable — they are different words to the
    line-breaker even though a reader sees almost the same thing.

    Used by the line breaker to recognize light verbs and enclitics, which is why
    punctuation goes but the ezafe stays: «کرد» after «واکنش» is a compound verb,
    «کرد.» ends a sentence, and «واکنشِ» is neither.
    """
    return _PUNCT_RE.sub("", measurable_text(word)).strip().lower()


# ---------------------------------------------------------------------------
# 2. Digits
# ---------------------------------------------------------------------------


def to_persian_digits(text: str) -> str:
    """ASCII and Arabic-Indic digits → Persian-Indic. Everything else intact.

    Only the ten digit glyphs are substituted, so separators, signs, decimal
    points, percent signs, and letters are preserved and the Unicode bidi
    algorithm keeps the substituted run correctly placed inside RTL text.
    """
    normalized = normalize(text)
    return "".join(
        _ASCII_TO_PERSIAN.get(ch) or _ARABIC_INDIC_TO_PERSIAN.get(ch) or ch
        for ch in normalized
    )


def to_ascii_digits(text: str) -> str:
    """Persian-Indic digits → ASCII. For numbers that must be parsed, not read."""
    return "".join(_PERSIAN_TO_ASCII.get(ch, ch) for ch in normalize(text))


# ---------------------------------------------------------------------------
# 3. Line-break analysis
# ---------------------------------------------------------------------------

#: Proclitics — bind FORWARD to the next word. A line must never END on one:
#: breaking after «به» strands the preposition from what it governs.
#: Matched on the whole cleaned word, never as a suffix, because suffix matching
#: false-positives on ordinary words ending in the same letters («کتابه» is not
#: «به»).
PROCLITICS = frozenset({
    "به", "از", "با", "در", "بر", "برای", "تا", "بی", "هر", "یه", "یک",
    "این", "اون", "آن", "چه", "که", "و", "یا", "اگه", "اگر", "وقتی", "چون",
    "روی", "زیر", "بین", "مثل", "طبق", "بدون", "علیه",
})

#: Enclitics — bind BACKWARD to the previous word. A line must never START on
#: one: they cannot lead a visual line on their own.
ENCLITICS = frozenset({"رو", "را", "هم", "دیگه", "دیگر", "ام", "ات", "اش"})

#: Explicit ezafe. This codebase writes the ezafe vowel out («واکنشِ», «خودِ»)
#: rather than leaving it implicit, so a word ending in one of these marks is
#: grammatically bound to the word after it — never break there. Checked against
#: the RAW word (only NFC-folded), because `compare_key` strips punctuation and
#: must not be allowed to eat these marks first.
_EZAFE_ENDING = re.compile(r"(?:\u0650|\u0654|\u06c0|\u0647\u200c\u06cc|\u0647\u06cc)$")

#: Light-verb conjugations of Persian compound verbs («احساس کنه», «شنیده نشه»).
#: The light verb behaves as an enclitic: alone at a line start it strands from
#: the nominal part of the compound. Matched by shape rather than an exhaustive
#: conjugation table, and length-capped so it cannot swallow unrelated words.
_LIGHT_VERB_MAX_VISIBLE_LEN = 6
_LIGHT_VERB = re.compile(
    r"^(?:ن?می\u200c?|ب|ن)?(?:کن|ش|د|زن|گیر|خور|باش|کرد|شد)(?:م|ی|ه|یم|ید|ن|ند)$"
)

#: Words after which a break is CHEAP — a natural pause the eye expects.
_CHEAP_BREAK_AFTER_WORDS = frozenset({"اما", "ولی", "پس", "چون"})
_CHEAP_BREAK_AFTER_PUNCT = ("،", "؛", ".", "!", "؟", "…", ":")


class BreakClass(Enum):
    """How acceptable a line break immediately AFTER a given word is.

    Deliberately three-valued rather than a numeric cost. In a raggedness-
    minimizing line breaker the objective is a sum of squared slack, which runs
    into the thousands; any penalty small enough to be a "preference" is noise
    against it, and any penalty large enough to matter is a constraint wearing a
    costume. So the grammatical rules are FORBIDDEN (pruned from the search) and
    the stylistic ones are PREFERRED (a real, bounded bonus).
    """

    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    PREFERRED = "preferred"


def is_light_verb_conjugation(word: str) -> bool:
    """True when `word` looks like the light verb of a Persian compound verb."""
    stripped = measurable_text(word)
    if not stripped or len(stripped) > _LIGHT_VERB_MAX_VISIBLE_LEN:
        return False
    return bool(_LIGHT_VERB.match(stripped))


def ends_with_explicit_ezafe(word: str) -> bool:
    """True when `word` carries a written ezafe binding it to the next word."""
    return bool(_EZAFE_ENDING.search(normalize(word).rstrip()))


def break_class(word: str, next_word: str | None) -> BreakClass:
    """Classify a break between `word` and `next_word`.

    `next_word` is None at the end of the text, where a break is trivially
    allowed. The three FORBIDDEN rules are the ones a Persian reader perceives
    as a typesetting error rather than a stylistic choice.
    """
    if next_word is None:
        return BreakClass.ALLOWED

    current = compare_key(word)

    # Never end a line on a proclitic, or on a word bound by written ezafe.
    if current in PROCLITICS or ends_with_explicit_ezafe(word):
        return BreakClass.FORBIDDEN

    # Never start a line with an enclitic or a stranded light verb.
    following = compare_key(next_word)
    if following in ENCLITICS or is_light_verb_conjugation(next_word):
        return BreakClass.FORBIDDEN

    # Natural pauses: after sentence/clause punctuation, or a contrast word.
    if normalize(word).rstrip().endswith(_CHEAP_BREAK_AFTER_PUNCT):
        return BreakClass.PREFERRED
    if current in _CHEAP_BREAK_AFTER_WORDS:
        return BreakClass.PREFERRED

    return BreakClass.ALLOWED


@dataclass(frozen=True)
class BreakViolation:
    """One forbidden break found in an already-laid-out block."""

    line_index: int
    word_index: int
    word: str
    next_word: str
    reason: str


def find_break_violations(lines: list[list[str]]) -> list[BreakViolation]:
    """Audit a laid-out block for forbidden breaks.

    Takes the lines a renderer actually produced and reports every break that
    violates a grammatical rule. Used by the reviewer stage and by tests, so a
    layout regression is caught as data rather than by eyeballing a frame.
    """
    violations: list[BreakViolation] = []
    for line_index, line in enumerate(lines[:-1]):
        if not line:
            continue
        next_line = lines[line_index + 1]
        if not next_line:
            continue
        last, first = line[-1], next_line[0]
        if break_class(last, first) is not BreakClass.FORBIDDEN:
            continue

        current = compare_key(last)
        if current in PROCLITICS:
            reason = f"line ends on proclitic «{last}»"
        elif ends_with_explicit_ezafe(last):
            reason = f"line ends on explicit ezafe «{last}»"
        elif compare_key(first) in ENCLITICS:
            reason = f"line starts on enclitic «{first}»"
        else:
            reason = f"line starts on stranded light verb «{first}»"

        violations.append(
            BreakViolation(
                line_index=line_index,
                word_index=len(line) - 1,
                word=last,
                next_word=first,
                reason=reason,
            )
        )
    return violations


def split_words(text: str) -> list[str]:
    """Split a cue into words, preserving explicit "\\n" as its own token.

    A literal newline in source text is an authored break hint, so it survives
    tokenization instead of being collapsed into whitespace.
    """
    tokens: list[str] = []
    for chunk in normalize(text).split("\n"):
        tokens.extend(w for w in chunk.split() if w)
        tokens.append("\n")
    if tokens and tokens[-1] == "\n":
        tokens.pop()
    return tokens


__all__ = [
    "ZWNJ",
    "ZWJ",
    "RLM",
    "LRM",
    "INVISIBLE_FORMAT_CONTROLS",
    "LETTER_FOLDS",
    "PERSIAN_DIGITS",
    "SENTENCE_PUNCT",
    "PROCLITICS",
    "ENCLITICS",
    "BreakClass",
    "BreakViolation",
    "normalize",
    "measurable_text",
    "visible_length",
    "compare_key",
    "to_persian_digits",
    "to_ascii_digits",
    "is_light_verb_conjugation",
    "ends_with_explicit_ezafe",
    "break_class",
    "find_break_violations",
    "split_words",
]
