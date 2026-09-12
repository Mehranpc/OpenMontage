# Film Type — current default: 2.13.0 / layout 13

This is a visual profile for the Persian footage pipeline. It is not a new
pipeline, runtime, narration mode, or approval.

**One current default.** Every unpinned `persian-footage` run resolves to
`2.13.0` / `layoutVersion 13`. If any other document, comment, or memory tells
you a different version is current, it is stale and this file wins.

**Read before composing:**

| Purpose | File |
| --- | --- |
| What 2.13 changed and why | `docs/persian-film-type-2.13-patch.md` |
| Archived 2.5–2.12 guidance (reproducing old pins only) | `skills/pipelines/persian-footage/film-type-history.md` |
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

Supported pairs are `2.1.0`/layout 1 through `2.13.0`/layout 13, each with its
exact canonical hash. The archived 2.12 hash is
`3580543858c134902cf1539fccf6d66e31f870d88a0b39a41ed1a28603f7aa5a`; the
current 2.13 hash is
`c742b5f13b71e504f40c3dda03625aafee4d533f1c66464045d82b21fecc683a`.

Older pins keep their own versioned behaviour. Never relabel a snapshot, edit a
frozen hash or sidecar by hand, or migrate projects in bulk. Migration means
resolving a fresh unpinned design and rerunning preparation.

## What 2.13 changed

2.13 keeps 2.12 subject-region and measured brand-separation safety, then adds
coverage and caption guarantees for production review:

1. **Watermark coverage is measured over the whole film.** The first 5 seconds
   stay clean. For videos at least 20 seconds long, visible coverage below 70%
   is refused and 80% is the target; 70–80% produces an advisory. For shorter
   videos, the floor is bounded by the post-intro time that can physically exist.
2. **Coverage planning may leave unsafe gaps.** The planner searches timeline
   intervals and alternate zones; it never weakens supplied subject/text geometry
   just to keep the brand visible. Normal dwells remain at least 6s. If a video
   under 20s has less than 6s available after the intro, its one legal dwell may
   use that entire remaining window.
3. **Long-form relocation is a target, not a safety gate.** At 30s and above the
   planner prefers multiple safe zones and at least two relocations when geometry
   permits. Missing that target is advisory when measured safety and coverage pass.
4. **Burned captions are physically centered in 2.13.** The larger horizontal
   safe-side inset is mirrored so the caption band center is exactly 0.5. Pinned
   2.12 keeps its historical asymmetric geometry.
5. **Opening hooks keep semantic content under layout pressure.** A moment authored
   as `kind: hook` + `purpose: hook-pattern-interrupt` must remain clause-level copy;
   automatic fallback below three lexical tokens is refused. A deliberately short
   user-authored hook is the only exception, recorded by `userAuthoredShortHook: true`.
   Automatic one-word copy cannot manufacture impact with `accentWords` or inline
   emphasis. Re-edit placement, crop/window, shot, or copy instead.
6. **Opening footage carries explicit semantic evidence.** A visual event declared
   `narrativeRole: hook` preserves its semantic role/direction and selected-window
   evidence through asset review, edit decisions, compose props, and preflight. The
   production `reward_problem_hook` role accepts only parent-to-child reward,
   child resistance/distress, or parent-child conflict directions and requires the
   reviewed subject plus visible human presence; reversed gift direction is not an
   equivalent opening.
7. **Caption boundaries and preflight evidence are machine-checkable.** Automatic cue
   repair never crosses a completed sentence/question/exclamation, including a
   terminator followed by a closing quote such as `؟»`. Preflight reports opening
   semantic/hook evidence, physical caption centering, hard-boundary status, and the
   watermark union coverage, floor/target, gaps, slots, relocations, and zones. These
   measurements are evidence only; final candidates still stop at `awaiting_human`.

2.12 is archived unchanged at `styles/persian-footage/film-type-2.12.0.json` and
remains pinnable. Reproduce it with `docs/persian-film-type-2.12-patch.md`; read
`docs/persian-film-type-2.13-patch.md` for the current patch.

## Subject safety: supplied geometry, never detection

Film Type still has no built-in face/person detector or classifier. The edit supplies
normalized envelopes after crop and across camera motion. They are mandatory and
binding; during autonomous planning they are conservative machine estimates, while
the user reviews the final render rather than JSON boxes. Missing geometry is a
refusal; a blocked phrase is not permission to weaken a truthful region.
`subjectSafety` is `checked-against-supplied-regions` only after the dwell clears them.

When text cannot clear a centre-framed subject, shorten/narrow the display copy,
change the crop or shot, or deliberately pin an older profile for reproduction.
Never remove a truthful region to make a render pass.

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
the opening clean. Minimum visible dwell 6s, target 12s, at most 5 relocations, one
lockup at a time, fade to zero between slots. The brand stays at least one
measured lockup height from moment text; where no legal slot exists it is
explicitly suppressed and the warning names the interval. Movement is not copy protection.

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
