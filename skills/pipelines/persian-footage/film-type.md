# Film Type — current default: 2.15.0 / layout 15

This is the visual profile for the Persian footage pipeline. It is not a new
pipeline, runtime, narration mode, or approval path.

**One current default.** Every unpinned `persian-footage` run resolves to
`2.15.0` / `layoutVersion 15`. If another document, comment, or memory says a
different version is current, it is stale and this file wins.

**Read before composing:**

| Purpose | File |
| --- | --- |
| What 2.15 changed and why | `docs/persian-film-type-2.15-patch.md` |
| Archived guidance for old pins | `skills/pipelines/persian-footage/film-type-history.md` |
| Render geometry audit | `docs/film-type-visual-regression.md` |

`film-type-history.md` is archive-only. Historical statements such as "current
default" remain useful for reproducing a pin but never override this contract.

## Activate

Use `persian_compose` and the canonical `persian.moments[].segments` contract:

```json
{"version": 2, "profile": "film-type", "seed": "<project-id>-film-type-01"}
```
The producer resolves `styles/persian-footage/film-type.json` into a hashed
snapshot. Absent design is refused. Legacy is reachable only through the hidden
emergency opt-out `{"version":2,"profile":"legacy"}`.

### Pinning

To reproduce an old project, copy the entire resolved `design` object from its
successful props sidecar. `resolved`, `contentHash`, and `profileVersion` travel
together; relabeling a snapshot or editing a frozen hash is forbidden.

Supported pairs are `2.1.0`/layout 1 through `2.15.0`/layout 15. The archived
2.14 hash is
`f9a2bf8d73ed2f6cc32f7d70230008cde12ed5607af0895a485b3cb7b0378c54`;
the current 2.15 hash is
`1952d3479b0c9b742255c17587635b2b496c75e773daecd60e6f7b322cb02a5f`.

Older pins keep their historical renderer, character-limit, caption, and
watermark behavior. Migration means resolving a fresh unpinned design and
rerunning preparation; never rewrite an existing pin in place.

## What 2.15 changes

2.15 makes typography and watermark planning separate responsibilities. The
opening may be semantically strong and still fail visual typography QA; a safe
watermark never gets authority to change footage or editorial copy.
### Adaptive editorial typography

On the active 2.15 path, character count alone is **not** an acceptance gate.
`audit_moments(..., adaptive_pixel_typography=True)` preserves the authored
phrase and lets the real browser decide whether it fits. Legacy and pinned older
Film Type versions keep their historical character ceilings.

Agents may choose only curated recipe IDs registered in the profile:

- `editorial-hero-balanced`
- `editorial-hero-compact`
- `editorial-callout-balanced`

There is no free-form CSS, arbitrary font-size field, or agent-generated layout
recipe. The browser loads Estedad, measures the real glyphs, tries the versioned
ladder and approved column fractions, and validates safe-area geometry, line
budgets, stack height, and occupancy. `occupancyMax` is a hard fit boundary;
`occupancyTarget` and the lower occupancy preference influence ranking rather
than deleting otherwise legal copy.

The same hierarchy model applies to opening hooks and body callouts. Semantic
roles (`lead`, `hero`, `tail`, `source`) remain copy structure; the renderer
turns them into visual hierarchy using measured size, placement, and line
balance. If no curated measured candidate fits, the run fails closed instead of
rewriting words to satisfy a character proxy.
### Visual hook quality is independent evidence

Semantic hook quality does not certify the pixels. A passing rendered opening
must carry `visualTypography` evidence from `rendered_opening_pixels`, including
a curated `recipeId`, measured occupancy, duration, and explicit hierarchy,
emphasis, line-balance, and optical-placement checks.

The production front door renders the opening first, runs the blind cold-view
and visual-typography review against that opening, and only then permits the
full candidate render. Review remains SHA-bound and context-isolated; authoring
metadata is never evidence for what a cold viewer sees.

## Subject safety and placement

Typography may still consume reviewed `avoidRegions`. Film Type has no face or
person detector; the edit supplies normalized subject envelopes after crop and
camera motion. Missing required review geometry or a blocked explicit text
placement is a typography refusal, not permission to weaken the region.

This subject-safety contract belongs to editorial text only. It must not leak
into watermark planning.

## Watermark — fixed anchors, text geometry only

2.15 accepts only four brand anchors: `upper-left`, `upper-right`, `lower-left`,
and `lower-right`. The planner receives no subject/face/body/footage regions.
Its authoritative blockers are the platform safe area plus measured editorial
text and, when active, burned-caption rectangles.
Coverage, intro delay, dwell, relocation limits, and measured brand-to-text
clearance remain hard policy. The first five seconds stay clean. If no legal
text-clear slot exists, the mark may be absent for that interval. Watermark
recovery may never request an asset swap, scene rewrite, subject segmentation,
or editorial-copy mutation.

## Safe area, contrast, captions, and motion

The active profile retains the conservative vertical safe area and the local
per-row contrast treatment from the prior generation. Burned captions remain
script-authoritative, one/two lines, physically centered, and suppressed while
an editorial moment is active. Caption geometry participates in watermark
collision planning; subtitle wording never becomes editorial moment copy.

All type is measured with the vendored Estedad fonts. The renderer still owns
the versioned ladders and animation grammar; agents do not set raw CSS sizes.
`lib/persian_film_verify.py` remains the Film Type frame verifier. Legacy accent,
scrim-plateau, shared-anchor, and orange-ink recipes do not certify Film Type.

## Production lifecycle around Film Type

The profile is consumed by the canonical Persian workflow, whose relevant order
is `no_copy_preflight → render_opening_candidate → opening_review →
render_final_candidate → master_final_candidate → final_review →
awaiting_human`.

True-peak mastering happens before the final candidate SHA is authoritative.
Final review, render report, checkpoint, and awaiting-human state are built by
canonical builders/commands, not hand-assembled JSON. Machine evidence never
constitutes human approval.
## Acceptance

Before merge, run the repository gates on the locked dependency tree:

1. targeted Issue #28 and Film Type contract tests;
2. full Python suite;
3. TypeScript `tsc --noEmit`;
4. repository lint and `git diff --check`;
5. real Chromium/Estedad browser-prepass tests;
6. GitHub CI with unresolved review threads at zero.

After merge, fast-forward Mac `main` to the exact GitHub merge SHA and run a
fresh real production smoke. Verify the opening-only gate before the full render,
then inspect the full Remotion/ffmpeg path, watermark schedule, mastering,
telemetry, finalization artifacts, and final `awaiting_human` stop.

Review `filmType.warnings` individually. Geometry preparation can prove fit and
policy compliance; it cannot approve aesthetics. Rendered typography QA must
look at hierarchy, occupancy, emphasis, line balance, optical placement, and
hold duration from pixels.

**A green machine run is not human approval.** Never set
`persian_text_verified` or human approval from successful preparation alone.
## Prohibited on 2.15

Free-form CSS recipes. Arbitrary font sizes. Copy rewriting to make layout fit.
Using word/character count as the adaptive-path render acceptance gate. Stroke,
outline, rectangular plates, backdrop blur, or a full-frame wash. Watermark
subject/face/body detection. Letting watermark failure mutate footage or scenes.
Editing frozen sidecars or hashes. Claiming visual or human approval from tests.

## Adding a version

A new registered version must update the profile snapshot, Python hash/version
registry, TypeScript union/hash/dispatch, painter branches, version-drift tests,
and a versioned patch note. The active routing docs must name exactly one current
default. Browser preparation and pinned-version reproduction tests must both pass
before the version can become unpinned default.
