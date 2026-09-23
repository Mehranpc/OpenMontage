## Film Type is the active visual profile

Film Type 2.16.0 / layout 16 is the default for every persian-footage run.
**This file does not restate the profile's rules.** Read
`skills/pipelines/persian-footage/film-type.md` for the active contract, and
`docs/persian-film-type-2.16-patch.md` for what the current version changed.
Guidance for older pins lives in
`skills/pipelines/persian-footage/film-type-history.md` — archive only.

Activate the active profile with
`persian.design = {"version":2,"profile":"film-type","seed":"<project-id>-film-type-01"}`;
the seed is derived from the project id.
All source, science, selective-moment, reading, coverage, sync, narration/music,
runtime, attribution and human gates still apply.
This routing is not Stage B completion, humanVisualApproval or C–E rollout.
Do not rewrite approved narration or facts to fit; request an editorial revision
when preparation refuses.

Absent design is REFUSED by persian_compose. `quiet-editorial` remains an
explicit option. Legacy is reachable only through the hidden opt-out
`{"version":2,"profile":"legacy"}`, for emergencies, never for new work.

Do not carry a safe-area value, field strength, contrast floor, anchor
tolerance or watermark position into this file. When those numbers live in two
places they drift, and an agent then applies Legacy geometry to Film Type.

## Archived guidance for older pins

See `skills/pipelines/persian-footage/film-type-history.md` for the archived
historical guidance. That archive is the source for understanding older pins;
this file does not repeat those rules.

# Executive Producer — Persian Footage Pipeline

## Minimal context routing

At bootstrap, read `profile-routing.md` and `review-policy.md`; do not preload every
director or `film-type-history.md`. Before each phase, read only
`phase-cards/<phase>.md`. Open that phase's director/reference only for the details
the card names. A phase transition discards the prior phase's working instructions.
This keeps the active prompt bounded while the manifest and checkpoint remain the
authorities for progression.

## Final-candidate protocol

Read `skills/pipelines/persian-footage/final-candidate-protocol.md` only when entering compose. Intermediate stages run autonomously; compose is the single post-render human gate.

## When To Use

The user wants a Persian (Farsi) video. Signals: the request itself is written in
Persian, or it names Persian/Farsi output, or it points at a source and asks for a
Persian result — «این مقاله رو بخون و یه ویدیو ۶۰ ثانیه‌ای بساز».

Route here rather than to `documentary-montage` or `animated-explainer` whenever the
on-screen language is Persian. Those pipelines are not wrong about montage or
explainers; they are wrong about Persian. They have no Persian font, no RTL
handling in their caption components, and they wrap text with CSS — which breaks
Persian lines at grammatically wrong points. Sending Persian work through them
produces output that is neither readable nor beautiful, which is exactly the
failure this pipeline exists to fix.

Route **away** from here when the content is English or another LTR language, even
if the user is Persian-speaking. `animated-explainer` and the rest remain fully
available and are the better fit there.

## What this pipeline produces

Real stock footage carrying **designed typographic moments**, plus platform-native caption delivery when the production profile calls for it. Moments and captions are separate systems.

- **Estedad** at real vendored weights (500/700/900) — never a synthesized bold.
- **7–9 moments in a 60-second video**, each a figure, a term, a claim, or a hook —
  the opening moment declares `kind: "hook"` and is the video's opening. The default
  hook style is claim+qualifier; a flat one-size style exists for an unsplittable
  single clause. Production pattern-interrupt hooks preserve clause-level meaning
  under layout pressure; automatic one-word fallbacks are refused unless the user
  explicitly authored a micro-hook. The selection rule,
  the style definitions, and every sizing value live in the hook section of
  `skills/pipelines/persian-footage/edit-director.md` and in
  `remotion-composer/src/persian/tokens.ts` — read them there, not here. Empty frame
  sits between moments. The narration carries the sentences; the type carries
  what the ear cannot hold.
- **Per-moment placement.** Placement is authored/reviewed per moment. The shared
  right column and anchor `993.6px` belong to the Legacy renderer and its verifier,
  not Film Type.
- **A local diffuse field**, supporting the active text group. Film Type frame QA uses
  a `4.5:1` contrast floor in `lib/persian_film_verify.py`. Legacy's
  `SCRIM.peakAlpha` `0.72` and `5.6:1` floor live in `tokens.ts` and
  `lib/persian_verify.py` and must not be applied to Film Type.
- **Script-authoritative captions.** `sidecar_only`, `burned_captions`, or `hybrid`;
  Instagram / Instagram Reels defaults to hybrid. ASR supplies timing only. Burned
  captions are one/two lines, yield to moments, preserve hard sentence/question
  boundaries, and use the active profile's platform-safe layout.
- **A semantic opening contract.** Hook footage carries reviewed semantic direction,
  subject/human presence, and selected-window evidence; a visually reversed action is
  rejected rather than accepted as generic emotional stock.
- **A bounded fixed-anchor brand watermark.** On Film Type 2.15 the planner may
  use only the four approved corner anchors. Safe-area plus measured editorial
  text/caption geometry are authoritative; subject/face/body regions are deliberately
  ignored by watermark planning. Unsafe text-collision intervals may remain blank,
  and watermark recovery never swaps footage or rewrites a scene.
  `WATERMARK_TOP_FRACTION` is a Legacy model, not the Film Type watermark model.
- **Motion** from a defined grammar: four spring weights, arrival/exit verbs, and
  a living-hold that never transforms settled glyphs.

Vertical 1080×1920 by default. Landscape 1920×1080 for long-form YouTube; the same
components serve both, with type scales set per format rather than scaled from one.

### What it deliberately does not produce

An authored wall-to-wall `cues[]` layer or karaoke track. The old system made transcript
copy a second independent design layer and allowed it to collide with hooks/moments.
That shape remains refused. The current burned-caption path is different: it is derived
from approved narration at render time, has a bounded one/two-line layout, yields to an
active moment, and cannot carry independent copy. Sidecar SRT remains available for
accessibility/indexing; hybrid adds pixels for muted-feed comprehension rather than
pretending burned text replaces the sidecar.

## Legacy renderer geometry — NOT Film Type

These values verify the Legacy renderer. Applying any of them to a Film Type
render is a bug, not a stricter check.

- **Legacy scrim peak:** `SCRIM.peakAlpha = 0.72` — definition at `remotion-composer/src/persian/tokens.ts:181`; consumed by `remotion-composer/src/persian/components/PersianMomentBlock.tsx:166`; the Legacy verifier also documents it at `lib/persian_verify.py:44`.
- **Legacy contrast floor:** `5.6:1` — `lib/persian_verify.py:193` (`SCRIM_GUARANTEED_CONTRAST`); the Film Type verifier uses `4.5:1` at `lib/persian_film_verify.py:72–74`.
- **Legacy moment zone / plateau:** `MOMENT_ZONE_FRACTION` — `lib/persian_verify.py:118`; `SCRIM_PLATEAU_MARGIN_PX = 28` — `remotion-composer/src/persian/tokens.ts:714` and `lib/persian_verify.py:270`; Legacy optical centre is derived as `44%` vertical / `50%` landscape by `remotion-composer/src/persian/tokens.ts:698–700`.
- **Legacy stack-height budget — per-format, NOT a contradiction:** `maxStackFraction = 0.58` vertical (`remotion-composer/src/persian/tokens.ts:568`) and `0.62` landscape (`:577`), consumed only by the Legacy fitter at `tokens.ts:683`. Film Type carries a single `maxStackFraction = 0.6` for both formats — `styles/persian-footage/film-type.json:92` — read by `remotion-composer/src/persian/filmType/layout.ts:176` straight from the resolved profile, never from `tokens.ts`. That `0.6` is byte-identical in every snapshot from `film-type-2.1.0.json` through 2.11 and no patch doc has ever changed it, so these are two independent per-profile budgets, not drift. Do not "reconcile" them; changing either one is a behaviour change to that renderer and needs its own visual review.
- **Legacy anchor/ink tolerances:** `ANCHOR_TOLERANCE_PX = 32` — `lib/persian_verify.py:152`; `INK_OVERSHOOT_PX = 8` and `INK_OVERSHOOT_EM = 0.065` — `lib/persian_verify.py:252–253`.
- **Legacy watermark positions:** `WATERMARK_TOP_FRACTION` — `lib/persian_verify.py:167`; exact positions are vertical `17.0419%` quiet / `11%` resting and landscape `17.8211%` quiet / `8%` resting, as used by the Legacy verifier and its documented contract.
- **Legacy zone ink ceiling and falloff:** `ZONE_INK_CEILING = 0.35` (35%) — `lib/persian_verify.py:209`; `falloffFraction = 0.28` — `remotion-composer/src/persian/tokens.ts:186`, yielding the documented vertical falloff of `302px` recorded in the plateau-geometry discussion of `skills/pipelines/persian-footage/compose-director.md`.

## The two non-negotiables

Everything in this pipeline serves one of these. When a decision is ambiguous, ask
which one it serves.

### 1. Readability (خوانایی)

Persian has failure modes Latin does not, and each one has a specific defence:

| Failure | What it looks like | Defence |
|---------|-------------------|---------|
| Missing ZWNJ | «میکند» or «می کند» instead of «می‌کند» | Orthography gate at script stage |
| Arabic ي / ك | Letters that look right but break matching | `lib.persian_text.normalize` |
| Western digits | «2024» inside Persian text | `to_persian_digits` |
| Wrong line break | Line ends on «به», starts on «را» | DP breaker with grammatical constraints |
| Overflow / shrink | Text past its column, or mysteriously small | Canvas measurement + fit ladder |
| Too fast | Moment gone before it is read | Reading floor in `tokens.ts` (`MOMENT_READ_CPS` vs the sidecar's rate) |
| Unglossed acronym | «SHBG» alone on screen | `figure`/`term` moments require a lead or tail saying what it counts or names |

The reading rate for a moment is far below the sidecar subtitle's rate — the values
live in `tokens.ts` (`MOMENT_READ_CPS`) and `lib/persian_srt.py` (`MAX_CPS`) — and
the gap is the point: a moment is read in a glance *while the footage plays*, against
motion, with no second chance. A subtitle transcribes words the viewer is already
hearing.

### 2. Beauty (زیبایی)

Beauty here is not decoration; it is the absence of specific ugliness:

- **No frozen frames.** A settled beat still breathes — but only through the room
  (drifting light, background plate), never by transforming type.
- **No glyph shimmer.** Settled text changes only in glow alpha and brightness. A
  sub-pixel transform on Persian's thin horizontal joins produces visible edge
  buzz.
- **No mismatched footage.** A clip that contradicts the narration is worse than no
  clip. Beats with no honest footage become typographic — at most two per video —
  but a typographic beat is a near-black void plate of last resort, never a
  substitute for footage that exists, and it must carry typography throughout.
- **No stock-montage look.** A consistent static grade pulls unrelated clips
  toward one look.
- **No footage that lost the subject.** The video's subject appears in the first beat,
  the last beat, and at least 40% of footage beats. Without that quota a video about
  coffee becomes a video about a medical check-up, one defensible query at a time —
  which is exactly what happened before the rule existed.
- **No wall of text.** Empty frame between moments is part of the design, not a gap in
  it. Roughly half the runtime carries no type at all.

## Stages

| Stage | Director skill | Produces |
|-------|---------------|----------|
| `idea` | `idea-director.md` | brief — mode, format, duration, beat count |
| `script` | `script-director.md` | script — Persian text, gate-passed |
| `scene_plan` | `scene-director.md` | scene_plan — beats with English queries |
| `assets` | `asset-director.md` | asset_manifest — video clips + word timings |
| `edit` | `edit-director.md` | edit_decisions — moments, shots, watermark |
| `compose` | `compose-director.md` | render_report — the MP4 |

Read the stage director skill before working in that stage. Not optional: each one
carries constraints that are not derivable from the manifest.

## Production modes

Chosen at `idea` and recorded in the brief. The choice changes what later stages do,
so it must not be inferred later.

### `narrated` (default)

The user supplies Persian narration audio. Word timings come from transcribing that
audio, but ASR wording is discarded as delivery copy. The approved script is aligned to
those timings and feeds the selected caption mode: SRT, burned pixels, or both. Because
burned/hybrid captions are timed to the narration, alignment accuracy is again visible
and is a hard pre-render gate rather than a cosmetic detail.

Only when narration audio is missing, hand the narration text to the user and wait
for audio as an input dependency. If final narration audio is already supplied,
transcribe it and continue autonomously to the rendered candidate.

### `silent`

No narration. Moment timings come from the beat structure; music carries the pace.
Choose this when the user wants a result without recording, or before narration exists.

There is no sidecar `.srt` in this mode, and that is correct rather than a gap: there is
no speech to subtitle.

There is a third case the pipeline does not pretend to handle: **synthesized**
narration. No TTS provider is configured in this installation (all ten report
unavailable). If the user wants synthetic narration, say that a TTS key is needed
rather than quietly falling back to `silent` — a video that silently lost its
narration is a broken promise.

## Footage rule: video only

**Still images are forbidden in this pipeline.** Not discouraged — forbidden. The
asset director rejects any manifest entry from an image source, and the contract
tests assert the rejection works.

The reason is that a still under Persian text reads as a slideshow, and the motion
grammar has nothing to work with: a camera move over a still is the Ken Burns
effect, which is a different genre from what this pipeline produces.

Sources are `pexels` and `pixabay_video`, through `direct_clip_search` with
`kind: "video"`. Search queries must be **English** — neither API indexes Persian,
so a Persian query returns either nothing or random results. Translating the
*visual intent* (not the words) is the scene director's job.

## Runtime lock

`render_runtime: "remotion"`, presented to the user at `idea` and carried through
`edit`. Presented, not assumed — AGENT_GUIDE.md's "Present Both Composition Runtimes"
rule applies here as everywhere, and both runtimes work on this machine.

The reason Remotion wins is specific to the code that exists, not to the runtimes. The
Persian text layer lives in `remotion-composer/src/persian/`: Estedad loaded through
`FontFace` inside `delayRender`, canvas measurement of every word before layout, a
dynamic-programming line breaker with grammatical constraints, and RTL containers with
explicit `direction`. Nothing equivalent exists on the ffmpeg path, and no HyperFrames
skill in this repo handles bidi or ZWNJ-aware breaking.

A silent swap produces a video with fallback-font layout — which looks *plausible* and
is wrong, the worst failure mode. If Remotion is genuinely unavailable, raise a
structured blocker. Do not swap.

`layout.ts` and `text.ts` were written runtime-agnostic — they take measured widths and
return line assignments, with no Remotion import — so a HyperFrames variant is real
work but not a rewrite. Treat that as a capability-extension request, never as an
in-flight workaround.

## Reviewer focus for this pipeline

Beyond the standard review in `skills/meta/reviewer.md`:

1. **Run the orthography gate.** `lib.persian_text` on every rendered string. Report
   violations as data, not impressions.
2. **Run the moment audit.** `lib.persian_moments.audit_moments` — pacing, gaps,
   coverage, per-kind limits. Read the `advisories` as well as the `problems`: the
   advisories carry the judgements the audit deliberately declines to enforce.
3. **Check the text coverage number.** Above 55% the audit fails it; anywhere near 55%
   is worth questioning by eye. This is the single number that distinguishes a
   typographic edit from a caption track, and it is invisible in the MP4.
4. **Use the verifier for the resolved profile.** Film Type renders use
   `lib.persian_film_verify.py`; its `verify_film_frames` checks synchronized
   sampled-frame contrast/composite evidence and does not apply Legacy plateau,
   anchor, or scrim assumptions. Legacy renders use `lib/persian_verify.py`, whose
   `verify_frames`, `anchor_report`, `check_moment_arrangement`, and `find_watermark`
   implement the Legacy geometry checks. A schema-valid `render_report` proves none
   of this, and neither does a hand-rolled brightness threshold — the
   compose-director records nine measured approaches that footage or the codec defeats.
5. **Check the subject quota.** First beat, last beat, and ≥40% of footage beats show
   the video's declared subject. Read the manifest's `selection_reason` lines: if they
   say "best match" rather than what is in frame, the quota was not actually checked.
6. **Count typographic beats.** Over the declared budget means footage sourcing
   gave up too early.
7. **Check attribution.** Both Pexels and Pixabay require it; a clip that cannot be
   attributed should not have shipped.
8. **Confirm `persian_text_verified` was earned, against the resolved profile's own
   evidence.** It is `false` out of `persian_compose` and may never be flipped by a
   tool. On Legacy it takes `verify_frames(...)["passed"]` plus an arrangement check.
   On Film Type those are the wrong instruments — `check_moment_arrangement` locates
   the hero by the Legacy accent colour and Film Type sets every role in white ink —
   so it takes `verify_film_frames` passing against the resolved props plus an actual
   painted-node or frame review of every moment, with reading order, gap emptiness and
   stack rhythm recorded as `not_checked`. `verification_notes` should carry numbers,
   not adjectives, and should name what was not verified as well as what passed.
