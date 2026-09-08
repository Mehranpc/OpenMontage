## Film Type 2.5 — soft shadow field and delayed brand

Current opt-in registry: 2.5.0/layout 5. Preserve 2.1/2.2/2.3/2.4 pins verbatim.
Fonts, wrapping, explicit placements, source content and approved edit times are
unchanged. Do not edit frozen hashes/sidecars to migrate; create a NEW input.

Arrival is frame-driven smoothstep with 18px travel for all text, including
cut-in (0.48s); soft-reveal remains 0.56s. Field and first text arrive together.
Reading/source gates and reveal delays remain authoritative; do not retime to
force acceptance. Number and unit stay in one authored reveal group.

The contrast field is a convex superellipse cloud with exact full-strength
support around the measured block, 4px padding and finite 300px feather, without
blur filters, a drawn card border, or footage grade. Soft/standard/strong are
0.5/0.6/0.7 over `#191919` blended as multiply, so footage hue survives and the
darkening dissolves outward like a soft shadow. Per-moment contrastStrength remains EXPLICIT direction, not an
automatic raw-footage luminance analysis. Check small text before choosing soft.

Brand planning uses shot/text/obstacle boundaries and a 6s fallback grid, min
6s dwell, target 12s, at most five relocations, and both sides when safe. It may
reuse a location. Fades remain inside safe dwells, with one lockup and no upper
slot or travel through subjects. The brand never opens the video:
`watermark.introDelaySeconds` (5) keeps the first seconds clean and the first
slot starts at the delay boundary. For films >=12s, inability to relocate fails
rather than silently producing a fixed/hidden mark. Short films may use one slot.
Single-side-only plans warn. The search refuses >512 timeline boundaries.
Movement is not copy protection. Empty avoidRegions is not independent visual
or contrast approval. Recheck the actual moving footage and Reels UI on the Mac.

First review three short native samples: title, figure and statement. Use RAW
staged footage, not a second overlay on an already-composited MP4. No new font,
layout, audio, provider or runtime design pass. Keep old projects/reviews intact.

### Historical contract for the named earlier versions

# Pathway Film Type 2.5 — the default path, Persian footage only

This is a visual profile, not a new pipeline, runtime, narration mode or approval.
Film Type 2.5 is the default: every persian-footage run carries a film-type design
unless explicitly directed elsewhere. `quiet-editorial` remains available as an
explicit option. Absent design is refused by persian_compose; the old Legacy render
is reachable only through the explicit hidden opt-out {"version":2,"profile":"legacy"}
(emergencies only). Do not migrate old projects in bulk, or call Stage B / C–E
complete. Human visual approval remains pending until real renders are reviewed.

## Activate (default for every new production)

Use the existing Remotion `persian_compose` path and the existing canonical
`persian.moments[].segments` contract. Choose:

```json
{"version": 2, "profile": "film-type", "seed": "<project-id>-film-type-01"}
```

The seed is auto-derived from the project id (deterministic per project).

Put this object in `persian.design` of the edit decisions. The producer resolves
`styles/persian-footage/film-type.json` into a hashed snapshot. To freeze a project
across future profile-file edits, copy the ENTIRE resolved `design` object from
the successful `.mp4.props.json` into `persian.design`, not the rest of the props.
All three pin fields (`resolved`, `contentHash`, `profileVersion`) are required
together. A changed snapshot/hash or unsupported version is refused. 2.5.0 keeps the 2.4.0 geometry, motion envelope, brand plan and timings, and
repaints ONLY the text field: a soft natural shadow blended as multiply over
footage, so the hue survives and the darkening dissolves outward gradually.
Supported
pairs are 2.1.0/layout 1, 2.2.0/layout 2, 2.3.0/layout 3, 2.4.0/layout 4, and
2.5.0/layout 5, each with its exact
canonical hash. The opt-in registry now resolves 2.5.0. Older pins keep their
versioned behavior; 2.1.0 uses its original breaker rather than inheriting the
accidentally shared 2.2.0 over-binding rule. Never edit a saved sidecar by hand.

Read this guide instead of applying the Legacy orange/glow/rule, fixed-right,
legacy silhouette, or oversized hero/tiny label styling. Existing shared
editorial, science, RTL, segment, coverage, music, sync, source and approval gates
still apply. No decorative `kicker`, detached `unit`, or mandatory eyebrow field.

## Editorial language across topics

Choose the application because of the information, not because of a topic ID:

- **Image-led title:** a short `hook` hero plus a closely related tail when needed.
  Example structure: `قهوه` / `و هورمون‌ها`. Related lines use a close size ratio and
  ink-based spacing. Do not add a vague lead just to fill a third line.
- **Quiet statement:** one compact hero; one useful support phrase only if needed.
  Prefer `inline-statement` for a calmer, small stack. This is not a caption track.
- **Pause / question:** a short thought with space around it. The shot carries
  emotion; the typography does not shout or decorate every word.
- **Quantity + context + source:** keep a complete number/unit phrase inside ONE
  authored hero, e.g. `۴۱ فرد سالم`. Its internal display may use two tightly bound
  rows. It never invents a `unit` field, detaches the unit to the side, reorders
  words, deletes a source, or rewrites the claim. A bare numeral remains a numeral.

Do not mechanically alternate treatments to satisfy a quota. Allow footage-only
intervals. No stock warning colors, unsupported causal claims, exaggerated hook
promises, automatic paraphrases, or topic stereotypes. Do not change approved
narration, facts, sources or music to fit a layout. Ask for an editorial revision
when fitting fails instead of deleting words or shrinking below the floors.

## Placement is reviewed geometry, NOT automatic face detection

Supported placements remain `upper-left`, `upper-right`, `mid-left`, `mid-right`,
`lower-left`, `lower-right`, `center`, `auto`. In 2.1.0 left columns align left.
In 2.2.0/2.3.0 non-centered Persian text aligns right WITHIN its authored column;
intentional center remains centered. Alignment does not move a block across the
frame. For right-anchored text / left-brand composition, explicitly change the
appropriate placements in a NEW review input, not by secretly mirroring them in
the renderer. Other projects and intentionally left-placed blocks are not migrated.
English brand text retains explicit LTR direction.

2.3.0 restores a 128px hook ceiling and the close 0.8 tail ratio. Its contextual
breaker permits complete display prefixes such as `قبل از` at the end of a line,
without weakening ordinary clitic or number/unit protections. Valid authored
breaks are preserved; it does not rewrite the sentence or insert forced breaks.

For `auto`, each overlapping shot must have reviewed `avoidRegions`, in normalized
screen coordinates AFTER cover crop, covering the subject/action across the entire
camera move and dwell. A reviewed clear shot is explicitly `avoidRegions: []`.
Missing metadata is not the same as reviewed-clear, and auto refuses to guess.
Regions have `x,y,w,h`; optional start/end are ABSOLUTE timeline seconds within
that shot. Omitted region times inherit the shot window; do not flatten them into
full-video exclusions or annotate a source frame without accounting for crop.

An explicit placement can be used without those regions, but subject QA is then
`not-checked` in the saved warnings. Supplied regions only prove clearance from
those envelopes, not successful face detection or a human visual approval. Safe
area and the motion envelope remain hard checks for every placement. Protect
faces, hands, key objects, charts and text already embedded in a clip as needed.

## Contrast and motion

Pure-white type, Estedad 700/500, no glow or mandatory decorative rule. Support
and source text are opaque, not lower-opacity grey. Inline emphasis, if explicitly
authored on the permitted hero, keeps white glyphs with a restrained blue underline.

A local, feathered Obsidian field supports the WHOLE active text group, including
small context/source lines. `contrastMode: light` deliberately uses dark glyphs
with a soft white field; it does not merely turn the dark field off. Prefer the
white-on-dark treatment unless the shot gives a considered reason to reverse it.

Optional `presentation.contrastStrength`: `soft`, `standard` (default), `strong`.
Choose once from the hardest part of the ENTIRE moment, not one representative
frame. There is NO automatic video luminance analysis and no frame-by-frame
pumping. Changing strength requires re-preparation, not editing a baked plan.
The `soft` option is not an excuse to accept unreadable small text. Inspect bright,
busy, moving and compressed phone-size output. If support darkens the subject too
much, relocate/re-edit the shot or text; a numeric ratio alone is not visual QA.

Film Type removes the Legacy always-on vignette/wash only in this explicit profile.
No main text = no main text field. Only 2.1.0 has independent brand support;
2.2.0/2.3.0 paint text-only branding, without a replacement card or shadow.
2.3.0 restores the original main-field plateau geometry (0.68, not 0.58), without
retiming text or changing footage grading.
Explicitly empty text AND empty brand = untouched footage
apart from the existing camera transform and encoding. Every field sits below
all text/brand ink; the brand's gradient must not darken another text block.

`soft-reveal` uses a short eased entrance and gentle upward arrival; `cut-in` is a
short opacity entrance without travel. Both are driven by Remotion frames, not
CSS timers. Authored `revealAfterSeconds` is retained and never pulled forward or decoratively delayed. Each actual reveal window, including a late source, must cover its reading charge and entrance/exit; otherwise preparation refuses and requests an explicit re-edit.
There are no letter-spinning, elastic scale, blur, looping or watermark bloom effects.

## Smaller, complete bilingual brand

At 1080×1920, 2.1.0 uses Persian 36px / Latin 28px. In 2.2.0/2.3.0 the sizes
are Persian 30px Estedad 500 / Latin 24px Arial 400, with a 6px line gap.
The full actual strings are measured in the browser. No clipping, ellipsis,
substring removal or emergency unreadable shrinking. Long brands that cannot fit
fail clearly. One relocation is the profile maximum, with at least six seconds
per dwell when two slots fit; geometry may reduce the count after revalidation.
A very short video has a single dwell. Only one lockup exists at any instant.
A fade to zero precedes the next slot, with full-dwell text/subject clearance.
2.3.0 first tries ONE position for the entire film, opposite the dominant authored
text column. It relocates only when no constant slot clears the complete timeline.
Upper slots are forbidden, not merely less preferred. The whole measured lockup
uses vertical insets top 14%, bottom 25%, left 8%, right 14%, plus the edge inset;
landscape uses symmetric 8% insets. These are internal review bounds, NOT a
universal official Instagram standard. Verify the actual Reels UI later.
Supplied obstacle clearance is not face detection or human approval; empty
avoidRegions alone is not independent visual evidence.
If no slot is safe, preparation fails instead of silently hiding the brand.

## Rendering and reopening a fresh review

The new prepass uses the already installed Remotion browser and the same shared
layout code as the component. It does NOT need `node-canvas`, and
`PERSIAN_SKIP_OPTIONAL_BRIDGE` cannot disable this mandatory measurement. The
production renderer remains Remotion. No dependencies or lockfiles are changed.

The exact prepared props, profile hash, normalized boxes, glyph baselines, source
text, placement warnings and brand schedule are saved BEFORE render in the
existing permanent `.mp4.props.json` plus digest. A later renderer remeasures and
refuses a stale/different layout rather than silently changing that sidecar.

For a short review that will be reopened in Studio or an actual-component DOM
harness, explicitly pass `keep_staged_assets: true` to `persian_compose`. This
retains THIS render's copied media after successful completion and returns its staging
folder. Failed renders clean their copied media, even with retention requested. It is off by default, uses disk space, never changes originals and does
not resurrect media already deleted from old runs. Keep the exact props and
copies until QA is finished. Afterwards remove only that identified staging
folder, not a project, source collection, or the whole `public/persian` tree.
Never point a review harness at cleaned-up aliases and mark the resulting error
as a containment pass. Await prepared metadata before mounting a raw Player.

## Required local acceptance before any broader rollout

1. Use at least three distinct real subjects and difficult shots, not endless
   re-renders of the breathing example or renamed screenshots.
2. Inspect native frames and moving phone-size cuts: title grouping, numeric/unit
   grouping, source legibility, bright backgrounds, field/subject interaction,
   RTL + Latin, each delayed reveal, and text-free intervals.
3. Verify actual painted descendants/ink, not just a planned wrapper. Check the
   complete brand, a deliberately long brand, before/during/after relocation,
   full dwell clearance and safe-area containment at every motion extremum.
4. Confirm source/narration/music unchanged. Do not interpret luminance QA as
   text-contrast, mobile or scientific validation.
5. Run the existing Persian suites and TypeScript checks on the locked local
   dependencies. Sampled regressions and synthetic stress fixtures are bounded
   technical evidence, not a replacement for these real-video gates.
6. Keep humanVisualApproval pending; keep quiet-editorial, other
   pipelines and C–E rollout unchanged. Legacy is disabled by default (hidden
   opt-out only) per the locked 2026-09-08 decision.
