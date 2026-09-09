# Film Type 2.11.0 — centred lower, denser brand shadow, calmer log

## Why

2.10 separated the letter edges at the glyph, but review of the 2.10 stills
showed three remaining problems:

1. **Text sits high.** The block centre (`middleCentre 0.49`) lands in the
   upper-middle of the frame, where faces and bright sky usually are. The
   brand lockup then competes for the same band.
2. **The brand is the weakest ink.** The watermark lockup is set at 30/24px
   with thinner strokes than hero type, so the text-level shadow
   (`nearAlpha 0.38`) under-separates it — and the field behind it has not
   been painted at all since 2.2, when the `{!polished && ...}` branch stopped
   rendering it. The brand's only protection was a shadow tuned for larger
   type.
3. **Edges run tight.** The nearest text/watermark edges sat within ~1% of the
   frozen safe area (watermark top `y = 0.145` against the `0.14` boundary,
   text right edge `x + w = 0.8307` against `0.84`), so any footage UI overlap
   reads as touching.
4. **The log repeats itself.** The same two advisories were emitted once per
   moment (14 warnings for a 5-moment film), burying the per-moment warnings
   that actually differ.

2.11 answers all four without touching the field, the strengths, or the safe
area:

1. **Lower block centre.** `layout.middleCentre` moves from `0.49` to `0.56`.
   No new code branch: `placeMoment` already clamps `y` to the ceiling
   `1 - bottom - (edgeInset + motionClearance) / H - h`, so short blocks land
   around 0.50–0.55 while the tall moment-1 block rests on its ceiling
   (≈ 0.428 with the new padding). The 0.50–0.62 band first proposed was
   mathematically impossible for tall blocks under the `y + h ≤ 0.65` browser
   constraint, which is why 0.56 was chosen.
2. **Brand-only shadow.** New `watermark.glyphShadow` token
   (near `2px / 5px / 0.50`, halo `18px / 0.26`), wired through a new
   `watermarkGlyphShadowFilter` with the same two-layer technique as text.
   The top-level text `glyphShadow` (`nearAlpha 0.38`) is untouched, and the
   `{!polished && ...}` field branch is untouched — legibility comes from the
   shadow, not from bringing back the wash.
3. **Edge padding as a separate token.** New `layout.safeAreaPaddingPx: 20`
   (≈ 1% of height, ≈ 1.9% of width), applied *in addition to* `edgeInsetPx`
   in the fit width, the `x`/`y` clamp, `inSafe`, and the watermark slots —
   and only for 2.11+, so pinned renders keep their geometry. It was
   deliberately **not** implemented as a `safeArea` change: two tests freeze
   the exact safe-area values, and the safe area is a platform contract while
   this margin is a taste choice.
4. **Aggregated warnings.** The two repeated per-moment advisories become one
   global warning each with a moment list
   (`... (moments: m1, m2, m3, m4, m5)`). Nothing is dropped, only de-duplicated:
   14 → ~4. Two misspelt `not_checked` strings become the contractual
   `not-checked`.

What is explicitly **not** introduced: no stroke/outline, no rectangular text
card, no backdrop blur, no frame-wide grade, no face or person detection, no
classifier, no network dependency, and no change to typography, strengths,
field size, timing, wrapping, thresholds, or watermark policy.

## Tokens (everything else identical to 2.10)

| Token | 2.10.0 | 2.11.0 |
| --- | --- | --- |
| `layout.middleCentre` | 0.49 | **0.56** |
| `layout.upperCentre` | 0.32 | 0.32 (unchanged) |
| `layout.safeAreaPaddingPx` | — | **20** |
| `watermark.glyphShadow.color` | — | `#191919` |
| `watermark.glyphShadow.nearOffsetPx` / `nearBlurPx` / `nearAlpha` | — | 2 / 5 / 0.50 |
| `watermark.glyphShadow.haloBlurPx` / `haloAlpha` | — | 18 / 0.26 |
| `contrast.glyphShadow` (text) | 2 / 6 / 0.38, halo 22 / 0.22 | unchanged |
| `contrast.strengths` | soft 0.24 / standard 0.34 / strong 0.40 | unchanged |

`profileVersion` `2.11.0`, `layoutVersion` `11`, profile hash
`ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687`.

The 2.10 profile is archived untouched at
`styles/persian-footage/film-type-2.10.0.json` (hash
`60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0`).

Real `y` ceiling for moment 1 (`h = 0.19688`) after the padding:
`1 - 0.35 - (10 + 20 + 18)/1920 - 0.19688 ≈ 0.428`.

## Behaviour inherited from 2.10 (unchanged)

- Typography and the brand are kept inside the **platform safe area only**
  (top 14%, bottom 35%, left 8%, right 16%).
- Subject-region enforcement stays **off**; every moment reports
  `subjectSafety: "not-checked"`. Nothing is ever silently reported as
  reviewed.
- The field stays small, per-row, diffuse, ungraded, bounded by the frame.

## Test contract notes

- `tests/lib/test_persian_film_type.py` moved to 2.11: the registry-default
  test asserts `2.11.0` / `11`, the supported-snapshots row for 2.10 now pins
  the archived `film-type-2.10.0.json` with `SUPPORTED_FILM_TYPE_210_HASH`,
  and a `2.11.0` row pins the live `film-type.json`. The
  wrong-layout-version list was updated because `11` is now a legal version.
- `tests/lib/test_persian_reels_safe_area.py` is untouched: the safe-area
  values are frozen, which is exactly why the padding is a separate token.
- `tests/lib/test_persian_ranked_browser.py` keeps the `y + h ≤ 0.65`
  constraint; only hard-coded snapshot `y` values move.
- `tests/lib/test_film_type_version_coverage.py` needs no edit: its purpose
  is to fail when a version is missing anywhere, and 2.11 is now registered
  everywhere.
- A pure refactor moved `canonical_numbers` from inside `resolve_design` to
  module level in `lib/persian_design.py` (body character-for-character
  identical) so the profile hash can be computed directly; two gates
  (via-API and direct, both `60ff5e80… MATCH`) proved behaviour unchanged.

## Verify

```bash
python -m pytest tests/lib/ -q
cd remotion-composer && npx tsc --noEmit && cd ..
# then the browser suite (same path that gave 7 tests before)
```

A green test run is **not** visual approval. Re-prepare and re-render, then look
at the stills yourself: the 2.10 render is superseded by these tokens. Nothing
is marked verified automatically, and `persian_text_verified` must never be set
by a script.

If moment 3 or 4 reads worse after the move down, the only permitted lever is
`watermark.glyphShadow.haloAlpha` from `0.26` toward `0.30`. Enlarging the
field or pushing `strong` above `0.40` is forbidden.

## Follow-up: reviewed regions steer the brand (2.11-only)

After the first 2.11 render, two face collisions were reviewed by eye against
the stills (no detection of any kind — hand-drawn boxes on this project only):

- shot-1 (0–4.38s): face box `{x 0.27, y 0.28, w 0.39, h 0.21}`;
- shot-7 (37.4–47s): face box `{x 0.05, y 0.10, w 0.90, h 0.20}`.

Two corrections to the first report came out of this:

1. **m1's `y = 0.22156` is NOT on the ceiling.** m1 is authored
   `upper-right`, so its path is `clamp(upperCentre − h/2, …) =
   clamp(0.32 − 0.09844) = 0.22156`, strictly inside `[0.15563, 0.42812]`.
   `middleCentre` never enters an explicitly upper-placed block; only the
   clamp bounds (which the new padding tightened) apply.
2. **2.11 text ignores regions by frozen design** (`enforceSubject === false`,
   "never use regions to reject, dim or move approved text"). Supplying the
   shot-1 box provably leaves m1's rect bit-identical, and no authored
   placement clears that wide block from that central face — so the m1
   overlap is reported, not silently fixed. A regression test pins both
   halves: 2.8 moves text out of a region, 2.11 does not.

What DID change (2.11 only, no token touched):

- `planWatermark` consumes reviewed regions twice: region-heavy zones sink
  in the candidate order (preference), and `clear()` vetoes a (zone,
  interval) pair that overlaps a region (refusal). When nothing clear fits
  the text, the existing "No safe moving watermark schedule" error fails
  loudly — the brand is never parked on a face, hidden, or shrunk.
- 2.9/2.10 pins plan exactly as before (their `subjectAvoid` stays `[]`,
  and the full-frame-region contract still renders: an empty lockup plans
  nothing, so the veto never fires).
- The shared legibility warning is now version-neutral
  (`Film Type 2.10+ legibility…`).
- 2.11 validates `watermark.glyphShadow` at prepare time (fail-loud); the
  paint path no longer falls back to the text shadow silently. Older pins
  are unaffected.

Production result on this project: the 34.02–47s brand slot moved
`upper-right → upper-right 34.02–37.4 + mid-right 37.4–47`, clearing the
shot-7 face box; the 5–19.4s slot moved `mid-left → lower-left`. Zero
planned slots overlap a reviewed region. m1's text is unchanged (see above).

## Rollback

Pin the previous profile explicitly in the project design block:

```json
{
  "version": 2,
  "profile": "film-type",
  "seed": "<unchanged project seed>",
  "profileVersion": "2.10.0",
  "contentHash": "60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0",
  "resolved": "<contents of styles/persian-footage/film-type-2.10.0.json>"
}
```

Pinning `2.8.0` additionally restores reviewed-region enforcement.
