# Estedad — vendored Persian typeface

Five static weights of [Estedad](https://github.com/aminabedi68/Estedad) by
Amin Abedi, licensed under the SIL Open Font License 1.1 (see `OFL.txt`).
The `fvar`-carrying variable build is deliberately **not** vendored: the
Persian composition pins discrete weights so a render never depends on a
variation-axis default that differs between Chrome versions.

| File | `usWeightClass` | Role in the Persian composition |
|------|-----------------|---------------------------------|
| `Estedad-Thin.ttf`   | 100 | (unused; kept so the family is complete) |
| `Estedad-Light.ttf`  | 300 | (unused; kept so the family is complete) |
| `Estedad-Medium.ttf` | 500 | subtitle body, captions, watermark |
| `Estedad-Bold.ttf`   | 700 | subtitle highlight, section titles |
| `Estedad-Black.ttf`  | 900 | hook line, hero typographic beats |

## Why real weights instead of synthetic bold

`Estedad-Medium.ttf` reports `usWeightClass: 500` with `head.macStyle` bit 0
clear, so it is a genuine medium — not a bold. Asking the browser for
`fontWeight: 700` while only the Medium file is registered makes Chrome
synthesize a faux bold by smearing outlines, which on Persian joined script
thickens the connecting strokes unevenly and closes small counters. Loading
Bold and Black as their own `FontFace` entries at their declared weights
avoids synthesis entirely.

## The ZWNJ trap (load-bearing)

Estedad's `cmap` has **no glyph for U+200C (ZWNJ)** — nor for U+200D, U+200E,
U+200F, U+2026, or U+2022. Verified by walking the format-4 subtable: every
one of those code points maps to glyph 0.

This does not break rendering. ZWNJ is a default-ignorable format control, so
the browser applies its joining behaviour and paints nothing — «می‌روم»
displays correctly. It **does** break measurement: `CanvasRenderingContext2D
.measureText()` can charge a `.notdef` advance for an unmapped code point, so
a width computed over a string containing ZWNJ may exceed the width actually
painted. The line-breaker then believes a line overflows when it does not, and
shrinks the whole block for no reason.

Therefore: **strip ZWNJ before measuring, keep it in the painted string.**
`lib/persian_text.py` (`measurable_text`) and the composition's `measureText`
helper both do this, and a test pins the invariant.

## Refreshing these files

Copy the upstream release's static TTFs over the ones here and keep `OFL.txt`
unchanged (it is the upstream licence text plus a provenance note). If the
glyph count or `usWeightClass` values change, re-run
`tests/contracts/test_persian_fonts.py`, which asserts the properties the
composition relies on rather than trusting the filenames.
