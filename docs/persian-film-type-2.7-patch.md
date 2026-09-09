# Film Type 2.7: diffuse shadow and honest diagnostics

## Installation
Apply AFTER the supplied 2.6 patch, from repository root. Preserve local work.

```sh
git apply --check /path/to/openmontage-film-type-2.7.patch
git apply /path/to/openmontage-film-type-2.7.patch
python -m unittest tests.lib.test_persian_film_type tests.lib.test_persian_film_verify -q
```

Rollback: `git apply -R --check ...` then `git apply -R ...`.
Unpinned film-type designs now resolve to 2.7/layout 7. Existing complete pins
remain pinned. Resolve a fresh design and rerun the official prepass; never relabel
hashes or reuse frozen rows. The previous default is archived as 2.6.0.

## Shadow
The new field uses a continuous Gaussian-like radial falloff with zero value and
slope at its finite rim, NOT a flat centre plus a narrow feather. Paint and planning
share diffuse27.ts. Shadow radius is independent of collision avoidance: we reduce
peak opacity, never collapse softness to 32px. Text still has hard subject clearance.
Subject shadow influence is checked at the nearest point of each supplied region
across entrance travel; maximum allowed opacity is 0.12. This is not image-adaptive
contrast or a guarantee of reading contrast. Low contrast needs footage review.
Old compact fields and frozen 2.6 layouts retain their interpretation.

## Region authoring and diagnostics
Record critical content, not a guessed silhouette: faces/eyes, active hands,
products, in-frame lettering, or body/clothing WHEN they carry the message.
Avoid regions remain hard for ink. Do not tighten them merely to make a run pass.
Other body areas may remain unprotected after explicit editorial review; this
patch does not add a new soft-region schema or automatic face detection.
Keep regions screen-space, timed and inclusive of camera movement/cuts.
Placement failures show up to three distinct sampled blockers (not an optimal
ranking). Watermark failures report attempted zone/dwell and text/subject index;
subject index follows shot order then avoidRegions order in the input. No region
is silently dropped. Explicit placement remains binding. Auto hooks get a small
lower-third penalty and any lower-third hook emits a review warning. An opening
statement is NOT automatically reclassified as a hook.

## Prepass errors / isolated probes
The worker emits OPENMONTAGE_PREPASS_ERROR JSON before the full stack. Python
surfaces that message. Browser cleanup exceptions are secondary warnings and
cannot replace the original error. The worker still writes the complete stack
to stderr; capture it when debugging.
For typography-only probes, make a disposable input copy with an explicitly empty
watermark and remove frozen filmType/watermarkPlan; retain all timeline shots and
review regions. Label the result DIAGNOSTIC ONLY. Never replace production props
with it. Reprepare the complete original brand/timeline before final rendering.
No skip-watermark flag is accepted on production props.

## Version-aware QA (required caller migration)
For Film Type, callers MUST pass the actual props:

```python
from lib.persian_verify import verify_frames
report = verify_frames(frames, props=prepared_props, evidence=evidence)
```

Without props, verify_frames retains the Legacy contract for compatibility; it
cannot infer a renderer version from pixels. Do not use that route, the Legacy
anchor/plateau checks, or the orange-accent gap detector to certify white Film Type.
The new route accepts paths/PIL images with EXIF normalization, or already upright
RGB arrays. Wrong aspect is rejected rather than rotated by guesswork.

Labels must be moment IDs. Each optional evidence[label] includes:
- seconds: exact absolute timeline sample time (stable fully revealed frame)
- background: same frame, same footage/shadow, with typography disabled
- footage: same frame with typography AND shadow disabled
- ink_mask: independently rendered text alpha array (H,W), float 0..1

Evidence must have identical dimensions, orientation, camera state and color path.
This patch does NOT add an automatic multi-pass evidence exporter. The director
must obtain synchronized diagnostic layers, or receive explicit not_checked.
Never estimate glyph masks by thresholding bright footage. No evidence means no
numeric certification, not a false 'scrim missing' failure. Checks include real
measured rect, sample stability, composite ink agreement, and conservative 4.5:1
contrast at the lower 5th percentile of opaque glyph pixels. Missing observable
shadow on dark footage is indeterminate, not proof that it did not render.

passed certifies ONLY these sampled checks; persian_text_verified remains false
because glyph order, semantic correctness, the full timeline and visual approval
are not proven. Empty evidence/samples cannot pass. QA does not fabricate universal
contrast guarantees. Watermark contrast and Film Type gap residue remain visual
checks until independent masks/backgrounds are provided by a dedicated exporter.

## Validation actually executed
- 43 Python contracts passed, including negative QA cases (absent text, low
  contrast, wrong geometry, absent observable shadow, wrong orientation, transient
  samples, missing evidence) and EXIF orientation handling.
- 22 direct Chromium assertions with real Estedad passed (both formats, variants,
  deterministic/frozen layouts, refusals, pinned 2.5 comparison).
- Actual React/Remotion typography preview on an extracted footage frame was
  inspected for the lower-position hook. This is a shadow diagnostic, NOT final
  approval of the user's migrated footage/regions, all frames, or watermark.
- Browser bundling/execution succeeded. Full repository TypeScript/full suite
  were not run successfully in this environment (missing dependency declarations).
- No new full 47-second production render or independent per-pixel evidence
  export was performed. Test synthetic QA fixtures are not footage certification.

Recommended acceptance: compare actual moment-1 and moment-4 footage, inspect
entry/stable/exit and crossed cuts, check moment-3 watermark on bright glass,
and resolve all editorial/contrast warnings without modifying measured geometry.
