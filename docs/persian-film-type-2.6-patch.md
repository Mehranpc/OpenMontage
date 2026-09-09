# Film Type 2.6 — ranked typography patch

## Install (repository root)

Start from the source archive supplied for this patch. Save local work first.

```sh
git apply --check /path/to/openmontage-film-type-2.6.patch
git apply /path/to/openmontage-film-type-2.6.patch
python -m unittest tests.lib.test_persian_film_type -q
```

Reverse, before making overlapping edits:

```sh
git apply -R --check /path/to/openmontage-film-type-2.6.patch
git apply -R /path/to/openmontage-film-type-2.6.patch
```

## Migration / behavior change

An unpinned `{ "version": 2, "profile": "film-type", "seed": "your-project" }`
resolves to 2.6/layout 6. Existing complete 2.1–2.5 snapshots keep their old
algorithms. The exact previous default is archived as film-type-2.5.0.json.
Do not manually change a pinned version or hash: resolve a fresh design through
normal compose. Regenerate the props sidecar; saved geometry is not reusable after
migration. Keep old projects pinned if exact historical reproduction is required.

2.6 deliberately refuses preparation if an overlapping shot has no reviewed
avoidRegions, including explicit placement. Review all shots across the text dwell
and camera movement. [] means reviewed clear footage, never an automatic migration
placeholder. Supply real regions or keep the old pin while review is pending.
When no ink-and-shadow-safe candidate exists, preparation fails with an actionable
message instead of silently covering the subject.

## Scope

- All Film Type moments and both supported formats use real-font candidate ranking.
- Three widths and the existing size ladder are evaluated. Extra hero lines,
  unequal line lengths, shrinking, height, footprint and placement preference
  contribute to a deterministic score. Existing minimum font sizes stay intact.
- Original text, punctuation, ZWNJ, newlines, roles, timing and sources are preserved.
- The contrast field has a bounded feather, reduced default strength, and a
  subject-clearance check covering its full conservative envelope and entrance.
- The pipeline editorial instructions now require semantic emphasis review,
  readable timed alternatives for long copy, and shot-by-shot visual review.
- Diagnostics request editorial/semantic/contrast review. They do not claim that
  successful preparation certifies beauty or footage contrast.

There is no new automatic face detector, semantic language model, narration rewrite,
beat retimer, or per-pixel contrast analyzer. Semantic role changes and splitting
approved copy into beats remain explicit editorial work before preparation. Empty
review regions cannot prove subject safety. Arbitrary-length text cannot always fit
at a readable size; refusal and re-editing are intentional. Legacy/quiet-editorial
rendering is outside the new ranker's scope.

## Verification performed for this patch

- 33 focused Python unittest contracts passed.
- 22 assertions executed in local Chromium with vendored Estedad and the actual
  compiled layout module: long hero preference, preserved text/roles, determinism,
  frozen round-trip, six phrases in each format, missing reviews, obstructed frame,
  oversized token, stale geometry, and old 2.5 output equal to pristine source in
  the SAME browser. Existing sidecar coordinates can differ across browsers; no
  historical cross-platform pixel identity is claimed.
- Five typography-only previews painted by the actual React/Remotion component
  were inspected on a neutral background. These are NOT approval of the supplied
  footage, subject regions, full animation, brand, or the complete final video.
- Full repository TypeScript checking was attempted but blocked by unavailable
  dependency/type declarations in this environment. Browser bundling and execution
  succeeded; this is not a substitute for a project-wide type check.
- The default pipeline test module could not run here because jsonschema was absent.
  No claim is made that the full project suite passed.

An additional repeatable integration suite is included (not run through the bundled
Remotion prepass here; the equivalent direct browser assertions above were run):

```sh
OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser
# Optional: REMOTION_BROWSER_EXECUTABLE=/path/to/chromium
cd remotion-composer
./node_modules/.bin/tsc --noEmit
```

The browser suite needs your existing composer dependencies and browser, but no
media downloads, API keys or provider calls. Without opt-in it reports skips, not
passes. Before production, render and inspect actual footage at entry/stable/exit
frames and crossed cuts. Inspect filmType.warnings before approving the video.
