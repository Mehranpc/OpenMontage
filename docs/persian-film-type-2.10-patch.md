# Film Type 2.10.0 — readable letters, smaller shadow

## Why

2.9 fixed the runaway wash: the field is now bounded by the frame and no longer
leaks outside the video. Review of the 2.9 stills showed the opposite problem on
bright footage (a lit window, a pale animal, snow): the remaining darkening is
soft and *large*, so it lowers overall contrast slightly without separating the
letter edges where readability is actually decided.

2.10 moves the work to where the eye looks:

1. **Per-row field.** Instead of one ellipse sized to the whole text block, each
   measured row gets its own small soft ellipse. A short line no longer drags a
   block-sized wash across the shot, and the darkening follows the real ink.
2. **Two-layer glyph shadow.** The glyphs themselves carry a close, tight shadow
   (edge separation) plus a wide, weaker halo (busy backgrounds). This is the
   cheapest legibility gain per unit of visual noise.
3. **Lower peak.** Because the field is smaller and the glyphs are separated, the
   `strong` peak drops from `0.44` to `0.40` — visibly *less* darkening overall,
   with better readability.

What is explicitly **not** introduced: no stroke/outline, no rectangular text
card, no backdrop blur, no frame-wide grade, no face or person detection, no
classifier, no network dependency, and no change to typography, geometry,
timing, wrapping, or watermark policy.

## Tokens (everything else identical to 2.9)

| Token | 2.9.0 | 2.10.0 |
| --- | --- | --- |
| `contrast.strengths.soft` | 0.26 | 0.24 |
| `contrast.strengths.standard` | 0.36 | 0.34 |
| `contrast.strengths.strong` | 0.44 | 0.40 |
| `contrast.diffuseField.radiusScale` | 1.05 | 0.85 |
| `contrast.diffuseField.minRadiusPx` | 220 | 180 |
| `contrast.diffuseField.perRow` | — | `true` |
| `contrast.diffuseField.rowPaddingPx` | — | 26 |
| `contrast.glyphShadow.color` | — | `#191919` |
| `contrast.glyphShadow.nearOffsetPx` / `nearBlurPx` / `nearAlpha` | — | 2 / 6 / 0.38 |
| `contrast.glyphShadow.haloBlurPx` / `haloAlpha` | — | 22 / 0.22 |

`profileVersion` `2.10.0`, `layoutVersion` `10`, profile hash
`60ff5e80524aaa3877e8bd94e2bdd8c957c9f367947066ced034cbfb8be678e0`.

## Behaviour inherited from 2.9 (unchanged)

- Typography and the brand are kept inside the **platform safe area only**.
  Subject-region enforcement stays **off**; `subjectSafety` remains
  `not_checked` and every prepared render still emits that warning.
- The field is bounded by the frame, so it can never be wider or taller than the
  video.
- Reels safe area: top 14%, bottom 35%, left 8%, right 16%.

## Verify

```bash
python -m unittest tests.lib.test_persian_film_type tests.lib.test_persian_film_verify tests.lib.test_persian_reels_safe_area -q
OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser
cd remotion-composer && ./node_modules/.bin/tsc --noEmit
```

A green test run is **not** visual approval. Re-prepare and re-render, then look
at the stills yourself: the 2.9 render is invalidated by these tokens. Nothing is
marked verified automatically, and `persian_text_verified` must never be set by a
script.

## Rollback

Pin the previous profile explicitly in the project design block:

```json
{
  "version": 2,
  "profile": "film-type",
  "seed": "<unchanged project seed>",
  "profileVersion": "2.9.0",
  "contentHash": "320a67a296d30cf1337b6c121cdd9367dfdc4e28fad1ba6af4f666e1e07551bf",
  "resolved": "<contents of styles/persian-footage/film-type-2.9.0.json>"
}
```

Pinning `2.8.0` additionally restores reviewed-region enforcement.
