# Script Director — Persian Footage Pipeline

## Your job

Write the Persian text when this stage is genuinely an authoring stage, and make it pass the orthography gate. In `narrated` mode, hand newly authored text to the user and stop.

## Authoritative-input / fidelity mode

When this director is entered through `skills/persian-video/SKILL.md`, the production front door already has authoritative Persian copy from an approved script or a faithful transcription of supplied narration. **Do not rewrite that copy.** In this mode your job is validation and canonical script-artifact packaging, not authorship.

- Preserve lexical wording and sentence order.
- Mechanical Persian letter/digit canonicalization may use the `normalized` policy defined by `subtitle-alignment.md`; it must not change words.
- If duration, orthography, or speakability fails a hard production gate, surface the blocker. Do not silently shorten, formalize, simplify, add a hook, or inject figures/terms.
- Requirements below that encourage figures, named terms, or hook-friendly phrasing are authoring guidance only. In fidelity mode they become diagnostics for later visual planning, never permission to alter approved copy.

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
or Arabic kaf ك (U+0643). They look nearly identical, and the renderer paints exactly
the bytes it is given — so an Arabic letter means the text on the frame is not the text
that was measured, fitted, and approved, while every check reports success.

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

The text is **not** going on screen sentence by sentence. It becomes narration, and a
sidecar `.srt` built from its word timings. What appears on the frame is 7–9
selected moments the edit director chooses — a figure, a term, a claim, or the
opening hook — so writing to a subtitle budget is writing to a constraint that no longer applies.

The opening line carries one extra obligation: it must contain a claim or figure the
hook can paraphrase honestly, because the hook may restate but never invent — the
honesty rule lives in the hook section of
`skills/pipelines/persian-footage/edit-director.md`, which is its single source.

That does not make length free. The narration still has to fit the duration, at roughly
**14–16 visible characters per second** of natural Persian speech. A 60-second video
carries something like 850–950 visible characters. Past that the narrator has to rush,
and a rushed delivery is audible in a way no gate catches.

Count with `lib.persian_text.visible_length`, not `len()`: ZWNJ and combining marks
cost nothing to read and must not be charged.

### Write the moments into the script's *content*, not its formatting

The edit director can only set in type what the script actually says. Two habits make
that possible:

- **State figures precisely and once.** «۲۲۶۴ نفر» in one sentence gives a figure
  moment its hero and its unit. «حدود دو هزار نفر» gives it nothing to set.
- **Introduce a term before leaning on it.** If the script says «SHBG» it should say
  what SHBG is, in the same breath — that sentence is what becomes the term moment's
  gloss, and a term moment without a gloss is refused.

Three or four figures and one or two named terms in 60 seconds is plenty. A script with
none of either yields a video with nothing specific to put on screen, and the edit
director will be reduced to setting sentences — which is the caption track this pipeline
exists not to produce.

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

No handoff. There is no narration and no sidecar `.srt`; the moments and the music carry
the video alone.

Write **much** less text. In narrated mode the script is spoken and the on-screen type is
a selection from it; in silent mode the only text a viewer ever gets is the moments
themselves. Seven to nine short moments is the whole script — a page of prose has
nowhere to go.

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
- Total visible characters fit the duration at 14–16 chars/second of speech.
- No sentence exceeds ~15 words.
- Every sentence has at least one legal break point.
- When this is a genuine authoring stage, the script contains enough precise figures or named terms for the edit stage to set useful moments in type. In authoritative-input/fidelity mode, absence of such material is not a reason to rewrite approved copy.
- In newly authored `narrated` mode: the text has been handed over and the stage has stopped. In authoritative-input/fidelity mode, package the validated copy and continue according to the production front door.
