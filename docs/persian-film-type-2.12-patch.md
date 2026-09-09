# Film Type 2.12.0 — reviewed subjects and measured brand separation

## Why

Two user-reviewed frames exposed separate missing contracts in 2.11:

- m1 placed a wide block across a face because 2.11 deliberately ignored reviewed
  regions for typography.
- m5 placed the two-line brand only **30.5px edge-to-edge** above the moment. The
  earlier 107px report measured top-to-top and was wrong. The planner's 12px
  collision margin proved non-overlap but did not prevent the two text systems
  from reading as one group.

The test video is not a delivery, so its existing m1 frame is not retroactively
blocked. The pipeline is fixed for every new unpinned run.

## Behaviour

- `profileVersion`: `2.12.0`; `layoutVersion`: `12`
- content hash: `3580543858c134902cf1539fccf6d66e31f870d88a0b39a41ed1a28603f7aa5a`
- `layout.autoRequiresReviewedAvoidRegions`: `true`
- `watermark.minTextClearancePx`: `64`
- `watermark.suppressWhenNoTextClearance`: `true`

Every shot overlapping a moment must carry reviewed normalized `avoidRegions`.
They reject typography candidates but no longer attenuate the diffuse field. If no
candidate clears the subject/action envelope, preparation fails with an editorial
remedy: shorter copy, another crop, or another shot.

The brand envelope is expanded by
`max(minTextClearancePx, measuredLockup.heightPx)` before it is compared with a
moment. For the default 77px-high lockup, the effective clearance is 77px. The old
12px `collisionMarginPx` remains the hard geometry/subject margin and is not
redefined.

The planner first searches for a full-dwell schedule satisfying the larger visual
clearance. If none exists but a hard-safe schedule does, intervals too close to text
are removed with the fade envelope. Remaining visible fragments shorter than the
6s minimum dwell are removed too. The output warning names every suppression gap.
If no visible dwell remains at all, preparation fails rather than silently deleting
the brand for the whole film.

## Compatibility

2.11 is archived byte-for-behaviour at
`styles/persian-footage/film-type-2.11.0.json` with hash `ee04b0e576891828d754b2dc8bc7139178174251e3755dea4797dd480df4f687`. Versions
2.1–2.11 remain pinnable and keep their original placement, subject, and watermark
behaviour. No safe-area, typography, contrast, motion, or shadow token changed.

## Acceptance

Run:

```bash
python -m pytest tests/lib/ -q
cd remotion-composer && npx tsc --noEmit && cd ..
OPENMONTAGE_BROWSER_TESTS=1 python -m unittest tests.lib.test_persian_ranked_browser -q
```

The browser suite includes both rejected geometries: reviewed m1 must refuse its
face collision, and m5 must contain no visible watermark slot inside its moment
unless the expanded measured envelopes clear. A green run is still not visual
approval; re-prepare and review the new stills at phone size.
