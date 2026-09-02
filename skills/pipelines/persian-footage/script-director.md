# Script Director — Persian Footage Pipeline

## Your job

Write the Persian text of the video, and make it pass the orthography gate. In
`narrated` mode, hand that text to the user and stop.

## Persian orthography — the mechanical rules

These are not style preferences. Each one, violated, produces text a Persian reader
sees as broken.

### ZWNJ (نیم‌فاصله, U+200C)

Required, not optional, in every one of these positions:

| Construction | Correct | Rule |
|--------------|---------|------|
| Present/negative prefix | «می‌روم», «نمی‌شود» | «می» and «نمی» take ZWNJ before the verb |
| Plural ها | «توییت‌ها», «کتاب‌ها» | ZWNJ before «ها» after most stems |
| Comparative | «دستی‌تر», «بزرگ‌تر» | ZWNJ before «تر» / «ترین» |
| Compounds | «هم‌کلاسی», «نیم‌فاصله», «پس‌زمینه» | ZWNJ at the seam |
| Suffix ی after ه | «خانه‌ی», «تجربه‌ی» | ZWNJ before the ezafe yeh |

Writing these with a full space breaks the word into two; writing them joined breaks
the letterforms. Both are wrong, and both are common in text copied from the web —
so text from a source document must be corrected, not trusted.

### Letters

Farsi yeh **ی** (U+06CC) and keheh **ک** (U+06A9) only. Never Arabic yeh ي (U+064A)
or Arabic kaf ك (U+0643). They look nearly identical and break every string
comparison, so highlight matching silently fails on them.

`lib.persian_text.normalize` folds them. Run it on everything, including text you
wrote yourself — an Arabic letter can arrive from a keyboard layout without you
noticing.

### Digits

Persian-Indic ۰–۹ (U+06F0–U+06F9). `to_persian_digits` converts ASCII and
Arabic-Indic, substituting only digit glyphs so separators and signs keep their bidi
class and numbers stay correctly placed inside RTL text.

### Punctuation

Persian comma «،», semicolon «؛», question mark «؟». Not their ASCII equivalents —
the ASCII forms have the wrong bidi class and jump to the wrong end of the line.

## Writing for the ear, then the eye

In `narrated` mode this text will be **read aloud by the user**. That constrains it
more than screen text:

- One breath per sentence. If you cannot say it without pausing, split it.
- No parenthetical clauses. They work on a page and collapse in speech.
- Numbers spelled as they are spoken.
- No sentence longer than about 15 words.

Then the same text becomes subtitles, which adds the reading budget: **21 visible
characters per second**. A sentence of 60 visible characters needs at least 3
seconds of narration. If your script has more text than the target duration allows,
cut the script — do not let the cue timing be squeezed. A cue the eye cannot finish
is the single most damaging readability failure.

Count with `lib.persian_text.visible_length`, not `len()`: ZWNJ and combining marks
cost nothing to read and must not be charged.

## Line-break awareness while writing

You do not choose line breaks — the renderer does, by measuring Estedad and solving
for balance under grammatical constraints. But you can make its job impossible.

The breaker will never end a line on a proclitic («به», «از», «با», «که», «و»…), never
start one with an enclitic («را», «رو», «هم»), never strand a compound verb's light
verb, and never break after a written ezafe. A sentence that is one long chain of
such bindings leaves it nowhere legal to break, and it escalates to shrinking type.

Practically: vary your sentence rhythm, and let clauses end. A sentence with a comma
in it gives the breaker a cheap, natural break point.

## In `narrated` mode: the handoff

When the script is written and gate-passed, present it as narration text and **stop**.

Say plainly what you need: the recorded audio file. Do not proceed to the scene
plan; do not offer to synthesize it. The pipeline resumes when the audio arrives.

Present it as clean readable text — one sentence per line, no markup, no beat IDs.
The user is going to read this aloud.

## In `silent` mode

No handoff. Cue timings will be derived from reading speed at the edit stage. Write
slightly less text than `narrated` mode would carry: with no voice setting the pace,
subtitles need more time on screen to feel unhurried.

## Verification before checkpoint

Run this and include the output in your checkpoint:

```python
from lib.persian_text import (
    BreakClass, break_class, normalize, split_words, visible_length,
)

for line in script_lines:
    assert normalize(line) == line, f"orthography: {line!r} changes under normalize"
    words = [w for w in split_words(line) if w != "\n"]
    # A sentence with no legal break at all will force the renderer to shrink.
    legal = sum(
        1 for i in range(len(words) - 1)
        if break_class(words[i], words[i + 1]) is not BreakClass.FORBIDDEN
    )
    assert legal > 0 or len(words) <= 4, f"no legal break point in: {line!r}"
    print(f"{visible_length(line):3d} visible chars | {line}")
```

Compare against `BreakClass.FORBIDDEN`, not the string `"forbidden"`. `BreakClass` is a
plain `Enum`, not a `str` subclass, so `break_class(...) != "forbidden"` is true for
every pair and the assertion passes on text that has nowhere legal to break — a check
that reports success unconditionally is worse than no check.

`normalize(line) == line` failing means your text carries Arabic letters, missing
NFC composition, or both. Fix the text — do not normalize it silently and move on,
because the same source will keep producing it.

## Success criteria

- Every line passes `normalize(line) == line`.
- Total visible characters fit the duration at ≤21 chars/second.
- No sentence exceeds ~15 words.
- Every sentence has at least one legal break point.
- In `narrated` mode: the text has been handed over and the stage has stopped.
