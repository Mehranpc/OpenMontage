# Film Type — current default: 2.11.0 / layout 11

This is a visual profile for the Persian footage pipeline. It is not a new
pipeline, runtime, narration mode, or approval.

**One current default.** Every unpinned `persian-footage` run resolves to
`2.11.0` / `layoutVersion 11`. If any other document, comment, or memory tells
you a different version is current, it is stale and this file wins.

**Read before composing:**

| Purpose | File |
| --- | --- |
| What 2.11 changed and why | `docs/persian-film-type-2.11-patch.md` |
| Archived 2.5–2.10 guidance (reproducing old pins only) | `skills/pipelines/persian-footage/film-type-history.md` |
| How to audit a render's geometry | `docs/film-type-visual-regression.md` |

`film-type-history.md` is an archive. It contains sentences such as "current
default" and "the registry now resolves" that were true when written. Do not act
on them.

## Activate

Use the existing `persian_compose` path and the canonical
`persian.moments[].segments` contract. Put this in `persian.design`:

```json
{"version": 2, "profile": "film-type", "seed": "<project-id>-film-type-01"}
```

The producer resolves `styles/persian-footage/film-type.json` into a hashed
snapshot. An absent design is refused. Legacy is reachable only through the
hidden opt-out `{"version":2,"profile":"legacy"}`, for emergencies.

### Pinning

To freeze a project against future profile-file edits, copy the ENTIRE resolved
`design` object from a successful `.mp4.props.json` into `persian.design` — not
the rest of the props. All three fields (`resolved`, `contentHash`,
`profileVersion`) are required together. A changed snapshot, a wrong hash, or an
unsupported version is refused.

Supported pairs are `2.1.0`/layout 1 through `2.11.0`/layout 11, each with its
exact canonical hash. The 2.11 hash is
`ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687`.

Older pins keep their own versioned behaviour. Never relabel a snapshot, edit a
frozen hash or sidecar by hand, or migrate projects in bulk. Migration means
resolving a fresh unpinned design and rerunning preparation.

## What 2.11 changed

2.11 keeps 2.10's fonts, wrapping, field strengths (`soft 0.24` / `standard
0.34` / `strong 0.40`), diffuse radii, motion envelope, and safe-area values.
It changes four things:

1. **`layout.middleCentre` 0.49 → 0.56.** Mid-placed blocks sit lower, away from
   the centre of the frame where faces usually are. `upperCentre` (0.32) is
   unchanged, so `upper-*` placements are unaffected.
2. **`layout.safeAreaPaddingPx: 20`** — a new token, separate from `safeArea`.
   It tightens the clamp bounds only; it does not change any safe-area value.
3. **`watermark.glyphShadow`** gives the brand lockup its own near shadow plus
   halo, so it stays legible on bright backgrounds. It is **required** in 2.11:
   if it is missing, both preparation and paint fail loudly. There is no silent
   fallback to the text glyph shadow.
4. **Reviewed avoid regions now steer the brand.** The moving-watermark planner
   deprioritises zones overlapping a reviewed region and vetoes overlapping
   (zone, interval) pairs outright. If no safe slot remains, preparation fails
   with "No safe moving watermark schedule" — it never hides or shrinks the mark.

## Subject safety: reviewed geometry, never detection

There is no face, person, or subject detection anywhere in this system, and no
classifier of any kind. Nothing may be added.

Supported placements: `upper-left`, `upper-right`, `mid-left`, `mid-right`,
`lower-left`, `lower-right`, `center`, `auto`.

`avoidRegions` are normalized screen coordinates AFTER cover crop, covering the
subject and action across the entire camera move and dwell. `x,y,w,h`; optional
`start`/`end` are ABSOLUTE timeline seconds within that shot, and omitted times
inherit the shot window. `avoidRegions: []` means a reviewed clear shot; missing
metadata is not the same thing, and `auto` refuses to guess.

**In 2.11, `enforceSubject` is OFF.** Consequences you must understand:

- Reviewed regions steer the **brand**. They do **not** move authored **text**.
- `subjectSafety` is therefore always `not-checked` in the saved warnings, even
  when you supplied regions. That warning is correct, not a bug. The system
  refuses to claim it checked something it did not check.
- A text block overlapping a subject is **reported, never silently corrected**.

### When text lands on a face

A wide block cannot be moved off a centre-framed face by placement. The safe
area leaves no clear column. Do not chase it with placement, weaker margins, or
a smaller size floor. Fix it editorially:

1. shorten the display copy so the block is narrower and shorter,
2. change or reframe the shot so the subject leaves the centre, or
3. pin that project to `2.8.0`, where subject enforcement is active.

## Safe area, contrast, and brand

Vertical safe area is top 14%, bottom 35%, left 8%, right 16%, plus
`edgeInsetPx 10`, `motionClearancePx 18`, and `safeAreaPaddingPx 20`. These are
internal review bounds, not an official Instagram standard. Verify against the
real Reels UI.

Type is pure white, Estedad 700/500. Support and source text are opaque, not
grey. The contrast field is a local diffuse cloud sitting below all ink;
`presentation.contrastStrength` is explicit editorial direction, chosen once from
the hardest part of the WHOLE moment. There is no luminance analysis and no
frame-by-frame pumping. `soft` is not permission to accept unreadable text.

The brand is bilingual, Persian 30px Estedad 500 / Latin 24px Arial 400, 6px
gap, measured in the browser with the real strings. No clipping, ellipsis, or
emergency shrinking; a brand that cannot fit fails. `introDelaySeconds 5` keeps
the opening clean. Minimum dwell 6s, target 12s, at most 5 relocations, one
lockup at a time, fade to zero between slots. Movement is not copy protection.

## Acceptance

Run all three, on the locked local dependencies:

1. `python -m pytest tests/lib/ -q`
2. `tsc --noEmit`
3. the browser suite

Then audit the render with `lib/persian_render_geometry.py` against the real
`.mp4.props.json`, and review every moment's entry, stable frame, exit, and each
crossed cut at phone size on bright, busy, and moving footage.

Review `filmType.warnings` individually. `editorial-review-required` and
`semantic-review-required` need an actual editorial decision.
`contrast-review-required` needs your eyes on each shot, not a geometry pass.

**A green test run is not success. Only the user's eyes approve a render.**
Never set `persian_text_verified` from sampled checks, and never report visual
approval from successful preparation, passing tests, or an empty region list.

## Prohibited

Stroke or outline on text. A rectangular plate behind text. Backdrop blur. A
full-frame grid or wash. Face, person, or subject detection. Any classifier. Any
network dependency. Setting `persian_text_verified` automatically. Loosening the
props guard. Changing any `safeArea` value. Editing a frozen sidecar or hash.
Claiming visual approval.

## Adding a version

A registered version must appear everywhere it is handled: the profile snapshot,
the hash map and version unions in `layout.ts`, the version lists in
`components.tsx`, and the `expected_version` map in `lib/persian_film_type.py`.
2.9 shipped missing from the `components.tsx` lists, fell through to the pre-2.4
painter, and drew a wash outside the frame — while every token-level test stayed
green. `tests/lib/test_film_type_version_coverage.py` now guards that gap. Write
a versioned patch note under `docs/`, and update the table at the top of this
file so exactly one version is ever described as current.
