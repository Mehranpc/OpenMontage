# Film Type 2.9 — safe area only, no required subject-region review

## Why

2.6–2.8 refused to place approved typography unless every overlapping shot
carried reviewed `avoidRegions`, and 2.7/2.8 additionally weakened the shadow
field (`fieldPeakAlpha` fell from `0.44` to `0.353`) whenever a supplied region
sat near the text centre. The only real product requirement is simpler: Persian
typography and the brand lockup must stay **inside** the Instagram/Reels safe
area. No detection of faces, bodies or objects exists anywhere in this pipeline,
and 2.9 does not add any.

## What changed

| Area | 2.8.0 | 2.9.0 |
| --- | --- | --- |
| `layout.autoRequiresReviewedAvoidRegions` | `true` | `false` |
| Auto placement without regions | hard error | allowed |
| Supplied regions block a placement | yes | no (kept for pinned ≤2.8) |
| `fieldPeakAlpha` with nearby regions | reduced (e.g. `0.353`) | full profile strength (`0.44` at `strong`) |
| Watermark planning obstacles | text rects + subject regions | text rects only |
| Upper watermark zones | allowed (2.8) | allowed |
| Safe area (vertical) | `top .14 / bottom .35 / left .08 / right .16` | unchanged |
| Typography, contrast ladder, motion, watermark tokens | — | unchanged |

Profile identity:

- `profileVersion` `2.9.0`, `layoutVersion` `9`
- content hash `320a67a296d30cf1337b6c121cdd9367dfdc4e28fad1ba6af4f666e1e07551bf`
- 2.8.0 snapshot archived at `styles/persian-footage/film-type-2.8.0.json`
  (hash `acfa082438f473f34f595a3a9132e03e26fda7dac0522f9c7ca00267272ac468`)

## What did NOT change

- The safe area is still enforced by `inSafe()` / `inWatermarkSafe()`. Text that
  cannot fit inside the safe area still fails loudly; nothing is clipped,
  hidden, ellipsised or shrunk below the profile floors.
- Real placement failures (copy too long for the column/height ladder) still
  raise `no readable Film Type placement fits ...`.
- Browser font measurement remains mandatory: no estimated metrics, no Legacy
  fallback, no network calls, no classifier, no QA bypass.
- `subjectSafety` reports `not-checked` under 2.9, and the prepass emits an
  explicit warning saying subject overlap is not evaluated. It is never silently
  reported as verified, and `persian_text_verified` is never set automatically.
- All older profiles (2.1.0 – 2.8.0) remain pinnable and behave exactly as before.

## Opt-in / opt-out

Because profile snapshots are hash-locked, the explicit opt-out is a pin:

```json
{
  "version": 2,
  "profile": "film-type",
  "seed": "<project seed>",
  "profileVersion": "2.8.0",
  "contentHash": "acfa082438f473f34f595a3a9132e03e26fda7dac0522f9c7ca00267272ac468",
  "resolved": { "...": "contents of styles/persian-footage/film-type-2.8.0.json" }
}
```

Without a pin, `{"version": 2, "profile": "film-type", "seed": "..."}` resolves
to 2.9.0 and needs no `avoidRegions` at all (`[]` or omitted are both fine).

## Files touched

- `styles/persian-footage/film-type.json` → 2.9.0 / layoutVersion 9 / gate off
- `styles/persian-footage/film-type-2.8.0.json` (new archive)
- `lib/persian_design.py` (2.9.0 registry entry, `SUPPORTED_FILM_TYPE_28_HASH`)
- `lib/persian_film_type.py` (bridge accepts layout version 9)
- `remotion-composer/src/persian/filmType/layout.ts` (2.9 branches, `enforceSubject`)
- `tests/lib/test_persian_film_type.py` (2.9 defaults + 2.8 pin regressions)

## Verification (run locally)

```bash
python -m unittest tests.lib.test_persian_film_type tests.lib.test_persian_film_verify tests.lib.test_persian_reels_safe_area -q
OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser
cd remotion-composer && ./node_modules/.bin/tsc --noEmit
```

Green tests are not visual approval. Render the sample project and review the
frames before publishing.
