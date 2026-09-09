## Film Type is the active visual profile

Film Type 2.11.0 / layout 11 is the default for every persian-footage run.
**This file does not restate the profile's rules.** Read
`skills/pipelines/persian-footage/film-type.md` for the active contract, and
`docs/persian-film-type-2.11-patch.md` for what the current version changed.
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

**Read this before the verification chapter.** Most of the measurement recipes in
this file are Legacy. `lib/persian_verify.py` locates type by the accent colour
`#FFC24B` and scopes every ink measurement to the scrim plateau. Film Type paints
white ink with a diffuse shadow and no scrim, so those two foundations are absent
— the affected checks do not merely become lenient, they cannot run at all. Never
apply Legacy scrim-ceiling, anchor-column, plateau or accent-detector rules to a
Film Type render, and never report a Legacy pass as a Film Type pass. Missing
synchronized diagnostic evidence is `not_checked`: not a pass, and not evidence
that the shadow failed. Do not set `persian_text_verified` from sampled checks.

# Compose Director — Persian Footage Pipeline

## Film Type 2.5 — historical default path

See `skills/pipelines/persian-footage/film-type-history.md` for the archived
historical guidance. That archive is the source for understanding older pins;
this file does not repeat those rules.

## Your job

Render the video, then **look at it**. A schema-valid `render_report` proves nothing
about whether the Persian is readable. Neither does a green measurement run: on the
active profile the measurable surface is smaller than it looks, and the eyes that
approve a render are the user's.

## Runtime routing — check before rendering

This pipeline requires `render_runtime = "remotion"`, locked at the idea stage after
being presented to the user.

If `edit_decisions.render_runtime` is anything else — in practice `hyperframes` —
**stop**. Do not rewrite the field and proceed. Surface the conflict, route the
decision back to the idea stage to re-lock it, log a `render_runtime_selection`
correction in `decision_log`, and resume.

The reason is specific and not a matter of preference. The Persian text layer lives in
`remotion-composer/src/persian/`: Estedad loaded through `FontFace` inside
`delayRender`, canvas measurement of every word, a dynamic-programming line breaker
that refuses to strand «را» or a proclitic, and RTL containers with explicit
`direction`. No HyperFrames skill in this repo provides bidi handling or ZWNJ-aware
line breaking. A HyperFrames render would fall back to system-font metrics and produce
text that looks plausible in a thumbnail and is wrong at every measured level.

`persian_compose` enforces this too — it refuses a non-remotion runtime rather than
quietly adapting — but the check belongs here as well, because by the time the tool
raises it the user has already waited.

## Render

```python
result = registry.get("persian_compose").execute({
    "edit_decisions": edit_decisions,
    "output_path": str(project_dir / "renders" / "final.mp4"),
    "crf": 16,
})
```

`persian_compose`, not `video_compose`. The Persian composition takes `shots` and
`moments`, not a cut list; `video_compose`'s adapters have no representation for a
moment's segment list, its hero ladder, or for Persian line-break constraints.

It also **gates the props before staging anything**. A retired `cues` or `hookText` key
at the top level, a retired `text`/`unit`/`label`/`kicker` key inside a moment, an
empty moment list, a pacing violation, an unanchored timing, or a moment whose
segments do not compose one phrase is refused in seconds rather than minutes into a
render. These gates are profile-independent: `audit_moments` runs from
`tools/video/persian_compose.py:801` before staging on every path, Film Type included,
and has no profile branch. If it refuses, the fix is at the edit stage — the error
names which rule and why. Two of those refusals deserve their own paragraph, because
the temptation to hand-fix them at the compose stage is strong and the remedy is
upstream:

- **A sync refusal means "re-derive", never "nudge".** `persian_compose` runs
  `lib/persian_sync.py`'s `audit_sync(moments, TimedWord.from_dicts(word_timings))`
  before staging. A refusal means the moment timings do not sit where the narration
  puts their own anchor words — the shipped failure this catches was a moment set
  rescaled by the duration ratio from a *different* narration, which preserved the
  shape of the old edit and drifted up to 3.41s against the new voice. The fix is
  `retime_moments` with the word timings, not editing `startSeconds` by hand until
  the audit stops complaining; hand-nudging produces a set that passes today's
  threshold and is still wrong at the next word.
- **A music refusal means the bed's licence record, not the bed.** Narrated mode
  requires a music bed; the refusal is about the record — a `musicTrack` with
  `license{name,url,downloadedAt}` and `contentIdRisk{level,reason}`. `high` risk is
  refused outright, `low` must cite the Pixabay Content Licence, and `unknown`
  needs an explicit `acknowledgeUnknownMusicRisk` decision. Deliberate silence is
  legitimate but must be stated as `omitMusicReason` — a silent delivery that was
  never decided is how the shipped video reached the user with no bed at all, and
  delivering without one and asking afterwards is the exact failure the gate
  exists to make impossible.

  One refusal here is a *shape* error rather than a licence error: the bed is
  stated **once**, as `persian.musicTrack`, and never also as
  `persian.audio.music`. The record is the single source of truth — the compose
  tool stages the file from `musicTrack.path` and builds the audio block itself.
  Stating both leaves the tool unable to tell which file the record licenses, so
  it refuses rather than guess; the fix is deleting the duplicate, not the record.

  The licence's honest limits, stated plainly in the record and the report: the
  Pixabay Content Licence permits commercial use and forbids standalone
  redistribution, and **no automated check can rule out third-party Content-ID
  claims on Instagram**. Record provenance (source, artist, licence name and
  URL, downloadedAt) so that a claim can be answered with the licence page; never
  promise safety that cannot be verified.

- **A pacing refusal with `needs X but has X`** — the same number on both sides,
  printed to two decimals — is the serialization floor bug, not an editorial
  fault. `retime_moments` derives exact ends (8.9455s), `to_props` carries them at
  1ms granularity, and round-half-even once landed the serialized copy at
  8.945s: half a millisecond below its own reading floor, so the compose tool
  refused a set that had passed every in-memory audit. The fix is in
  `to_props` (end rounds up, start rounds down — the span never undercuts the
  floor), not in the edit: re-run `retime_moments` and re-serialize; do not
  hand-add milliseconds to `endSeconds`.

Defaults worth knowing:

- **`crf: 16`** — soft large-area gradients and fine grain are the first two things a
  higher CRF destroys, and both profiles have one: the Legacy scrim and the Film Type
  diffuse field. Banding across a full-width gradient is very visible.
- **`timeout_ms: 60000`** — per frame. The default 30s can expire while a cold font
  cache loads Estedad.
- **`scale`** — below 1.0 for a quick check. Text is still measured at full size, so a
  half-scale render validates layout honestly, and `lib/persian_verify.py` scales every
  geometric check with the frame. Ship at 1.0.

It also writes a sidecar `.srt` beside the MP4 when `audio.wordTimings` is present, and
returns its path plus any readability advisories. Those are advisories on purpose: an
over-speed subtitle is a property of how fast the narrator spoke, and the honest remedy
is a shorter script, not a blocked delivery.

### Iterating cheaply

Disk on this machine is nearly full and renders are minutes long. Verify a section
before committing to the whole thing:

```python
inputs["frames"] = "0-120"     # first four seconds
```

Render one moment per shape — one lead-above-hero figure, one statement with a long
hero, one built moment with a late `revealAfterSeconds` — and the watermark's
migration. Four short renders find more problems than one long one, for less time and
less disk. On Film Type the watermark relocates, so a frame slice that contains no
relocation tells you nothing about the schedule; take the windows from the prepared
geometry's slot boundaries.

Pick the windows from the moment list, not at fixed intervals. Text now covers at most
55% of the runtime by design, so a blindly chosen window is more likely than not to
contain no type at all.

### Opening a real project's props in Remotion Studio

For visual iteration without rendering, open the composition in Studio with the
project's own props. The composition ids are `PersianFootageVertical` and
`PersianFootageLandscape` (registered in `remotion-composer/src/Root.tsx`); props
reach the composition through a props file, the same `--props=` file the compose
tool stages before rendering. Two caveats, both load-bearing:

- Footage must be reachable from the composer's public dir — Studio resolves
  relative sources against it, so an absolute path elsewhere will not paint.
- Never pass `--public-dir` to this pipeline. Overriding it hides
  `public/fonts/estedad/`, and the composition's `delayRender` then never resolves:
  the render hangs rather than failing (the mechanism is commented in
  `tools/video/persian_compose.py`, which stages clips under `public/` instead for
  exactly this reason).

## Verification — this is the actual work

A render that completes tells you the props were well-formed. It says nothing about
the two things this pipeline exists to get right.

**Choose the instrument by profile before you measure anything.**

| Profile | Verifier | What it measures |
|---|---|---|
| Film Type (active) | `lib/persian_film_verify.py`, `verify_film_frames` | prepared rect, contrast against a **4.5:1** floor (`:69–74`), shadow presence, composite. Its header states it makes no Legacy plateau or accent assumptions (`:1–5`) |
| Legacy (opt-out only) | `lib/persian_verify.py` | everything described in the rest of this chapter: scrim plateau, accent-located hero, anchor column, zone ink ceiling, stack rhythm, fixed-position watermark |

The Legacy recipes are documented here in full because they are the ones with a decade
of failure modes attached, and because the reasoning at each threshold is worth reading
before inventing a new check. But two of their foundations do not exist on the active
profile:

- **The accent colour.** `check_gap_is_empty`, `check_moment_arrangement` and `_dilate`
  all locate type by `#FFC24B`, whose channel spread of 180 no footage reproduces under
  a scrim. Film Type sets every role in white ink. There is no accent mask to build, so
  these three checks cannot be run against a Film Type frame — not strictly, not
  leniently. Running them anyway produces a confident answer about a colour that was
  never painted.
- **The scrim plateau.** Every ink measurement below is scoped to the rows the scrim
  darkens at `peakAlpha`. Film Type has no scrim: it uses a per-row diffuse field
  (`film-type.json:122–127`, `filmType/diffuse27.ts`), so `SCRIM_CEILING` describes a
  threshold that is not in the frame.

Where Film Type has no automated equivalent, say `not_checked` in the report and name
the check. A reviewer who sees only passes will assume the rest was covered.

Do not write your own pixel checks: the obvious ones do not work, and the section at
the end of this file records which ones were tried and what defeated each. That table
is profile-independent — the traps are properties of H.264 and of footage, not of a
profile.

### The moment model you are verifying

Moments are one **grammatical Persian phrase with one emphasised span**, expressed as
an ordered segment list — `[{role: "lead", text: "…"}, {role: "hero", text: "…"}]`.
The array order is the reading order, top to bottom, so «مطالعهٔ دانشگاه اولوی فنلاند
روی» is authored *before* «۲۲۶۴ نفر» because that is the order the sentence is said
in. This part is profile-independent. There is no arrangement table keyed by `kind` any
more, which is worth saying
aloud because the shipped render's defects were all arrangement-table defects: a
floating «نفر» at the hero's baseline (the unit is now *inside* the hero text, so the
satellite cannot exist), and a 133px vertical gap between the hero and its label
against a designed 26px — Estedad's 1.665em line box against a numeral's ~0.97em of
ink, half-leading masquerading as spacing. Rows are ink-trimmed against
canvas-measured `actualBoundingBox` extents in both profiles, so a declared gap is the
gap that appears; the rhythm measurement below is the Legacy proof that the trim
survived the render.

**Legacy sizing:** sizes derive from one ladder rung per moment — `HERO_LADDER_PX` in
`tokens.ts`, walked
from the top — with the lead, the source, and the inter-block gap all derived from
that rung via `computeLeadPx` and its siblings. A short hero lands on a big rung and
a long claim on a smaller one, and the proportions hold in both. Two hook-scoped
exceptions live in the same file: a claim+qualifier hook starts its walk below the
top (its large qualifier adds ink mass the ordinary heroes lack), sizes its
qualifier as a hook-scoped fraction of the hero, sets both lines in the same weight
class, gaps them from the qualifier's size, and staggers their arrival in two beats —
and the silhouette gate refuses a hook whose lines read as a block. That gate is
Legacy-only (`HOOK_SILHOUETTE_*`, `tokens.ts:478–481`, checked in
`tools/video/persian_compose.py:992+`; `filmType/layout.ts` does not import it). The
operational consequence belongs here, not just in the edit skill: on Legacy the flat
hook's line breaker balances lines, balanced lines measure outside the band by
construction, and a flat hook is therefore refused at compose time — do not treat a
flat hook as shippable on Legacy, even if it typeset. The flat-hook
exception is narrower: a flat hook (a hero-only moment carrying `accentWords`) is
typeset as a display block rather than as an emphasis span, so it may occupy more
lines and breathes on looser leading — the values live in `tokens.ts`.

**Film Type sizing:** the three ladders in `styles/persian-footage/film-type.json:51–71`
are walked in `remotion-composer/src/persian/filmType/layout.ts:297–301`, bounded by
`maxStackFraction` in the same JSON (0.6; the Legacy token in `tokens.ts` is 0.58 — a
real difference, not a rounding, so do not quote one at the other's render).

The Legacy verifier needs the fitted lead size for
the rhythm check below; the tool result carries no fitted sizes, so read the fitted
`stackHeightPx` off the props moments (`edit_decisions.persian.moments[].stackHeightPx`,
attached by `_maybe_attach_stack_heights` in `tools/video/persian_compose.py`) and
derive the lead from the fitted rung (see the rhythm snippet).

### Extract frames

Sample the middle of each **moment** — not the boundaries, where enter and exit
animations are mid-flight, and not at fixed intervals, which under this model mostly
lands on empty frames. For a **built** moment (one with `revealAfterSeconds`
segments), sample the last step's midpoint as well as the moment's, so the fully
built stack is what you measure. This sampling discipline applies to both profiles;
what changes is the function you hand the frames to.

```python
import subprocess
import numpy as np
from PIL import Image

frames = []
for moment in edit_decisions["persian"]["moments"]:
    n = int((moment["startSeconds"] + moment["endSeconds"]) / 2 * 30)
    path = f"renders/frames/{moment['id']}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "renders/final.mp4",
                    "-vf", f"select=eq(n\\,{n})", "-vsync", "0", "-frames:v", "1", path],
                   check=True)
    frames.append((moment["id"], np.asarray(Image.open(path).convert("RGB")).astype(int)))
```

Sample one frame from the middle of **every gap** as well, and measure those with a
different function. That separation is not tidiness — it is the correction of a real
mistake. A Legacy gap frame has no scrim, by design, so `ink_mask` sees raw footage and
returns
31-99% "ink"; feeding gap frames to `verify_frames` produced a confident scrim failure
(`contrast 2.93:1`, `anchor -85px`) on a frame that was correctly empty. Sample the
*middle* of the gap for the same reason you sample the middle of a moment: the scrim
leads the type in and trails it out over `SCRIM.fadeFrames`, so a frame near a boundary
is a legitimate partial state. On Film Type the analogue is the row's own
`arrive × leave` envelope rather than a scrim fade, but the boundary caution is the same.

**Legacy only:**

```python
from lib.persian_verify import check_gap_is_empty

for lo, hi in gap_spans:                      # including the head and the tail
    gap = check_gap_is_empty(frame_at((lo + hi) / 2), fmt)
    assert gap["passed"], gap
```

`check_gap_is_empty` measures **accent coverage**, the one ink findable with nothing
behind it: the accent's channel spread of 180 is a property of the colour rather than of
the contrast, and `accent_mask` admits 0.0000% of real footage. Real gaps measure
0.0000-0.0246%; a moment with its hero up measures in whole percentages. The ceiling is
0.5%.

On Legacy one honest limit shrank with the moment model, and the report should say so:
**every** moment paints an accent hero, including statements, so an overrun of *any*
kind into a gap is detectable — under the slot model a statement had no accent and its
bleed into a gap was invisible in pixels.

**On Film Type there is no accent ink at all**, so gap emptiness has no colour-separable
instrument. Do not substitute a brightness test: the abandoned-approach table below
records exactly why that fails on ungraded footage. Report gap emptiness as
`not_checked` and confirm it by eye on the sampled gap frames.

What is not detectable on either profile is stated in the result and repeated below:
intra-word glyph order.

### Measure them — Legacy

Everything in this subsection is `lib/persian_verify.py` and applies to a Legacy
render. For Film Type, run `verify_film_frames` from `lib/persian_film_verify.py`
against the resolved props and read its rect/contrast/shadow/composite result; its
contrast floor is 4.5:1 (`:69–74`), and it deliberately makes no plateau or accent
assumption (`:1–5`).

```python
from lib.persian_verify import verify_frames, scrim_plateau

fmt = edit_decisions["persian"]["format"]
# Scope every measurement to the scrim plateau — the rows the scrim actually
# darkens at peak alpha — not the zone envelope. The envelope is where type
# *may* land; the plateau is where brightness separates ink from footage.
# ``stackHeightPx`` is the fitted ``heightPx`` from layout; it ships per moment
# as ``stackHeightPx`` in the props (see persian_compose._build_props).
stacks = {m["id"]: m["stackHeightPx"] for m in edit_decisions["persian"]["moments"] if "stackHeightPx" in m}
# If stacks are not yet in the props (older renders), they can be derived the
# same way the component does: ``computeScrimPlateau(fmt, stackHeightPx)``.
summary = verify_frames(frames, fmt=fmt, stack_heights_px=stacks)
# Or per frame: ``measure_moment(frame, fmt, stack_height_px=height)``
# or ``measure_moment(frame, fmt, plateau_rows=(top,bottom))``
if not summary["passed"]:
    for problem in summary["problems"]:
        print(problem)
```

`verify_frames` (and `measure_moment` / `check_moment_arrangement` /
`measure_stack_rhythm` individually) returns `passed`, `problems`,
`frames_with_text`, and a per-frame measurement — scoped to the **scrim
plateau**, not the zone. The zone remains the envelope for watermark
clearance and height budgeting, but ink is measured only where the scrim
holds `peakAlpha` (``stackHeightPx/2 + 28px`` around the optical centre);
outside that band `SCRIM_CEILING` does not hold and bright footage would be
misread as type. Each problem names its own likely cause. What it checks,
and what each failure means:

| Measured (plateau-scoped, Legacy) | Failure means |
|---|---|
| Ink inside the scrim plateau | Font did not load (tofu has no ink where glyphs belong), or the moment did not paint on its darkened band |
| Line count, and each line at least `MIN_LINE_PX` tall (30/26) | The fitter and the renderer disagree about the line budget, or a "line" is really an artefact |
| Ink inside the text column, per-line allowance `INK_OVERSHOOT_PX` + `INK_OVERSHOOT_EM`×line height | Layout measured against a different font than the one that painted |
| Every line's right edge within 32px of the anchor column | The shared right edge broke — the one thing a reader notices immediately. **Legacy only: Film Type has no shared anchor**, it scores placement per moment in `filmType/layout.ts:276–310` |
| Contrast ≥ 5.6:1 (inside the plateau) | **The scrim did not render.** Not a grading problem — see below. The Film Type floor is 4.5:1 and is checked by `persian_film_verify` instead |

The plateau geometry is ``stackHeightPx/2 + SCRIM_PLATEAU_MARGIN_PX=28`` around
the optical centre (``computeMomentCentreFraction``: 44% vertical, 50%
landscape), scaled with the frame. TS exports ``computeScrimPlateau`` and
``SCRIM_PLATEAU_MARGIN_PX`` in ``tokens.ts``; Python mirrors them in
``lib/persian_verify.py:scrim_plateau`` / ``SCRIM_PLATEAU_MARGIN_PX`` and they
are pinned together by ``tests/contracts/test_persian_geometry_parity.py``. A
moment's own ``stackHeightPx`` (``FittedMoment.heightPx``) is the honest source;
the envelope height is not a substitute — it would grey 42% of the frame and
include falloff rows where footage passes ``SCRIM_CEILING`` (the falloff is
``falloffFraction·shorterAxis`` = 302px in vertical).

Two tolerances guard the same edge in opposite directions, and they are different
quantities. `ANCHOR_TOLERANCE_PX` (32) covers ink falling *short* of the anchor and is
sized to the glyph's right side bearing — blank space inside its own advance box, worst
case 20px on «۲۲۶۴» at 260px. Ink going *past* the anchor has two independent causes and
the allowance covers both additively: `INK_OVERSHOOT_PX` (8) for antialiasing and H.264
ringing, which do not scale with type, plus `INK_OVERSHOOT_EM` (0.065) of the line's own
run height for glyph **overhang past the advance box** — Chromium paints an initial «آ»
0.065em past where canvas `measureText` ends its advance (measured +15px on a 216px hero
on the real render; node-canvas `measureInk` sees none of it — the same DOM-vs-canvas
divergence the ZWNJ charge covers on the width axis). The 8px flat part alone was
measured at caption-era 80px type, where the overhang is ~5px and hides under it; at
216px it is 14px and the flat part alone failed a correct frame. A column that
genuinely broke still fails loudly: it runs to the frame edge, 86px away.

Read `anchor_offsets_px` even when the frame passes. It is one entry per line, so a
single stray line is visible instead of averaged away, and `worst_anchor_offset_px`
against the 32px tolerance is the margin you actually have.

The zone (`MOMENT_ZONE_FRACTION`) is now explicitly the envelope of the **tallest
legal moment** — `maxStackFraction` 0.58 of the usable frame height — which in
vertical is `{top: 0.230419, bottom: 0.649581}` and in landscape
`{top: 0.238211, bottom: 0.761789}`. The right anchor did not move: 993.6 in vertical
(safe-area margin). The left bound is derived, not pinned: the anchor minus
`computeLineBudgetPx`, which is why the drift margin moved it to 113.08 in vertical and
197.92 in landscape. The envelope is what
watermark clearance and the height budget derive from; the plateau is what ink
measurement is scoped to (one per moment, from that moment's own fitted height).
`check_gap_is_empty` remains zone-scoped — a gap has no scrim by design, so its
accent-based check works on raw footage and must not be plateau-scoped.

Film Type's equivalents are different numbers in a different file: a Reels safe area of
14/35/8/16 (`film-type.json:10–15`), `upperCentre` 0.32 and `middleCentre` 0.56
(`:94–95`), and `maxStackFraction` 0.6 (`:92`). Do not read a Legacy zone bound against
a Film Type frame.

The contrast floor is a derived guarantee, not a preference. `SCRIM.peakAlpha` is 0.72,
so footage of brightness `f` composites to at most `0.28f`, capped at `255 · 0.28 = 71.4`
for pure white footage. The three inks measured against 71.4 give 8.485:1 (primary),
6.022:1 (secondary), and 5.747:1 (accent) — so 5.6:1 is below the worst of them and
arithmetically unreachable while the scrim is painting *inside the plateau*. A reading
under it means the type is sitting directly on the clip. The brightest pixel in the
real render's vertical plateau measures exactly 71.4, which is the scrim working.

That derivation is what makes the Legacy floor a guarantee, and it is exactly what Film
Type does not have: a per-row diffuse field is conditional local contrast, not a
full-width alpha, so no arithmetic ceiling follows from it. `persian_film_verify`
measures the composite instead of deriving it, against 4.5:1. A Film Type run that
reports `contrast-review-required` is telling you that measurement, not the derivation,
is the only evidence available.

Contrast alone cannot catch a *missing* scrim, though, and that is the trap worth knowing:
against dark footage, unscrimmed white type still measures 15:1 and passes. So
`ZONE_INK_CEILING` is checked too — now on the *plateau* — if more than 35% of the
plateau is ink-bright, what is being measured is footage, not type. The densest real
moment fills 9.6% of the zone and a three-line statement 6.9%, so the ceiling has
wide clearance; plateau-scoped it is even more selective because the band is narrower.

`frames_with_text` empty across every frame is reported separately — that is either
wrong sampling or a failed font, and both are worth distinguishing from a layout fault.
Under this model an empty frame is normal: text covers at most 55% of the runtime by
design, so sample from the moment list's own timings and never at fixed intervals.

### Reading order — Legacy only

The measurements above cannot see reversed text: «است فارسی متن این» occupies nearly the
same pixels as the correct order.

`check_moment_arrangement` reads it from geometry, by locating the hero's rows through
the accent colour. **It cannot run on a Film Type frame**, where every role is white:
there is no accent mask to separate the hero from the neutral ink, so the check has
nothing to compare. Report reading order as `not_checked` on Film Type and read the
sampled frames yourself — a reversed phrase is instantly obvious to a Persian reader,
which is why the pixel check was only ever a safety net.

Its signature changed with the
segment model, because the old arguments named things that no longer exist — there is
no `unit` and no `label` to pass, and no `kind`-decided arrangement to assert. What it
takes now is the moment's own authored role sequence:

```python
from lib.persian_verify import check_moment_arrangement

for moment in edit_decisions["persian"]["moments"]:
    roles = [segment["role"] for segment in moment["segments"]]
    order = check_moment_arrangement(
        frame_for(moment["id"]), roles=roles, fmt=fmt,
        stack_height_px=moment.get("stackHeightPx"),
    )
    assert order["passed"], order
```

Run it on **every** moment, not one of them. The check no longer skips statements —
under the slot model a statement had no accent and nothing to locate, so it was the one
kind reading order was never verified on. On Legacy every moment paints its hero in the
accent, so every moment is verifiable, and the one you skip is the one that ships wrong.
The one exception is a flat-hook moment (a segment carrying `accentWords`): its accent
is inline on one or two words of a single block, so there is no accent block whose
rows could sit above or below anything — pass `flat_accent=True`, which reports the
carve-out explicitly rather than failing a correct frame.

It verifies, from the accent hero's rows against the neutral ink's rows:

- **The hero sits below every segment authored above it** — a lead must paint above the
  hero, which is the user-facing rule «مطالعهٔ دانشگاه اولوی فنلاند روی» above
  «۲۲۶۴ نفر», stated in the authoring order rather than in a layout table.
- **The hero sits above every segment authored below it** — tail and source paint
  below.
- **No neutral ink above the hero when nothing was authored above it.** This is the
  clause that would have caught the floating «نفر»: residue from a retired satellite,
  or a stray block painted in the space the lead should have occupied, is ink where the
  authored phrase says there is nothing. Under the old check that residue was *expected*
  — it was the unit, and the check was told to find it.

The hero is located by colour, which works here and nowhere else: the accent's channel
spread is 180 against 5 for the primary ink, and under the scrim no footage channel can
exceed 71 against the accent's red of 255. Both halves of that sentence are Legacy
preconditions — an accent hue, and a scrim capping the footage — which is precisely why
the check does not transfer.

Isolating the *neutral* ink then means subtracting the accent — and the subtraction has
to grow the accent mask first, because a glyph's antialiased rim is bright enough to be
ink and too far from `#FFC24B` to be accent. `_dilate` does that, with a **square**
structuring element, and the shape is the whole point. A cross-shaped dilation never
covers a diagonal neighbour at any radius, while a rim follows the glyph's outline — so
on every curve the rim sits diagonally from its own ink and survives. On the first real
run that left 43 stray pixels on the hero's own rows out to column 993, every one within
4px of accent ink, and the check reported a reversal on a frame that was correct. A
verifier accusing the thing it protects is the worst failure it can have; if you touch
`_dilate`, `TestDilate` is what holds the shape.

**What no profile can check: glyph order inside a word.** A string reversed character by
character produces ink of nearly the same extent. Correlating the ink profile against
the expected string shaped in the same font was tried: in a clean PIL rendering the true
profile beats its mirror by 0.86 correlation, and on the H.264 output that margin
collapses to 0.05-0.07 — a confident answer from noise. It is deliberately not
implemented, because a reading-order check that certifies the fault it exists to catch
is worse than none.

Intra-word order is covered where it can be: `tests/contracts/test_persian_text_parity.py`
pins normalization across both languages, and the composition sets each word as its own
span with `unicodeBidi: "embed"`, so ordering is the browser's bidi implementation rather
than arithmetic in this repo. That holds for both profiles.

### Vertical rhythm — the gap is the thing the user sees

The shipped render's most-photographed defect was not reversed text or tofu; it was a
133px vertical gap between the hero and the line below, against a designed 26px. The
cause was invisible in every token: Estedad's line box is 1.665em while a Persian
numeral's ink is ~0.97em, so stacking rows by their line boxes interleaves leading that
belongs to no glyph, and the slack depends on which glyphs are in the string — the
reason no line-height multiplier can fix it. That failure mode is a property of the
font, so it threatens both profiles; the composition trims rows to their measured ink
on both.

`measure_stack_rhythm` is the **Legacy** proof that the trim survived the render — it
needs the plateau to find its bands and the fitted lead size from the Legacy ladder, so
it has no Film Type equivalent. On Film Type, check the gap by eye against the prepared
row geometry, and report the rhythm as `not_checked`.

```python
from lib.persian_verify import measure_stack_rhythm

for moment in edit_decisions["persian"]["moments"]:
    # PSEUDOCODE for the first line — lead_px is the fitted lead size of THIS
    # moment's own rung (computeLeadPx(heroPx, fmt) in tokens.ts, where heroPx
    # is the rung fitMoment walked to). Neither the tool result nor the props
    # carry it; read the rung from the compose log, not from a sibling moment.
    # Scope to the plateau so falloff footage bands don't read as extra blocks.
    lead_px = ...  # fitted lead size for this moment's rung
    rhythm = measure_stack_rhythm(frame_for(moment["id"]),
                                  lead_px=lead_px, fmt=fmt,
                                  stack_height_px=moment.get("stackHeightPx"))
    assert rhythm["passed"], rhythm
```

It finds the ink bands in the plateau, measures the empty rows between consecutive bands,
and flags any inter-band gap above `round(lead_px × 0.55) + tolerance` — the designed
inter-block gap plus allowance. The check is **one-sided** on purpose: only
too-large gaps are faults. Descenders, the rule, and entrance-time blur legitimately
dip into the space between blocks, so a "gap smaller than designed" reading is normal
typography, not a defect; the failure this exists to catch is the half-leading leak,
which is always in the *loose* direction. The tolerance is generous in absolute px
because the designed gap itself is proportional to the lead (54px at the top rung, 30px
at the bottom), but a leak is not proportional — 133px against 26px was 5×, and any
genuine trim failure reads similar.

Run it on every moment frame you sampled, with that moment's own fitted lead size
(see the pseudocode note above — the tool result carries no fitted sizes, so the
rung comes from the compose log). Reusing one moment's lead for another's frame under-charges
the top-rung moments and over-charges the bottom-rung ones, and both mistakes look like
passes.

### Watermark

The watermark cannot be found by looking at one frame. It is white type at low opacity
with no scrim behind it, so it composites to roughly `0.6·255 + 0.4·footage` — a value
bright footage produces on its own. That much is true of both profiles, and so is the
remedy: an ablation render.

**Where the profiles diverge is whether the position is fixed.** On Legacy the mark has
two positions from `WATERMARK_TOP_FRACTION` and four phases. On Film Type it *moves*:
`planMovingBrand` in `remotion-composer/src/persian/filmType/watermark24.ts:7–44`
schedules slots around the prepared moment rects, bounded by `maxRelocations` 5,
`minDwellSeconds` 6 and `transitionSeconds` 0.3 from `film-type.json`, and it raises
"No safe moving watermark schedule" rather than overlapping type. So on Film Type there
is no single expected top fraction to pass in — take the slot boundaries from the
prepared geometry, sample one frame inside each slot, and check the mark is where the
schedule says and clear of that moment's rect. A single frame proves one slot, not the
schedule.

**Legacy:**

```python
from lib.persian_verify import find_watermark, WATERMARK_TOP_FRACTION

# Same edit_decisions, empty watermark, a few frames at the position you want to check.
reference = {**edit_decisions, "persian": {**edit_decisions["persian"],
                                           "watermark": {"persianText": "", "latinText": ""}}}
# render it with "frames": "100-104", pull frame 0, then:
top = WATERMARK_TOP_FRACTION[fmt]["quiet"]     # or ["resting"]
mark = find_watermark(frame, expected_top_fraction=top, reference=reference_frame)
assert mark["found"] and not mark["clipped_at_edge"], mark
```

Take the position from `WATERMARK_TOP_FRACTION`, not a literal — it is pinned against
`tokens.ts` by a contract test, so it cannot drift away from where the renderer draws.
Both positions moved up with the new zone, because the quiet position is derived from
the zone's top with a clearance margin and the zone is now the tall envelope:

| Format | Quiet | Resting | Phases (of `durationInFrames`) |
|---|---|---|---|
| vertical | 17.0% | 11% | quiet to 20%, bloom +60f, decay +60f, migration +45f |
| landscape | 17.8% | 8% | same |

Both positions sit above the moment zone in both formats — including at the bloom's
1.15 scale, which a contract test also checks. `clipped_at_edge` catches the
`translateX`/position pair drifting apart, which only shows on long text.

Without a reference, `find_watermark` works on a **footage-free** render (`shots: []`)
and refuses to guess on anything else. That is a cheap standalone check of all four
phases and the migration path, and it needs no second render of the real video — and it
is the cheapest way to inspect a Film Type schedule too, since an empty-footage render
shows every slot the planner chose.

Two things to know about the numbers it returns. On an MP4 pair the vertical extent is
exact but the horizontal extent widens by tens of pixels, because H.264 scatters
differences into neighbouring columns — enough for presence and clipping, not for
measuring width. And the mark's own soft shadow forms a faint halo contiguous with the
glyph rows, which is why the detector applies a floor relative to the strongest row;
without it the reported extent grows from 14 rows to 89. On Film Type the mark carries a
glyph shadow with a wide halo by design (`watermark.glyphShadow` in `film-type.json`),
so expect that halo to be larger, not absent.

Bright-background legibility of the mark is reviewed separately, by eye. No check in
either verifier certifies it.

### Sync and pacing — the numbers that were never measured

Two properties of the timeline are checked by gates rather than pixels, and they are
the two the shipped render got wrong, so they belong in the report even though no frame
can show them. Both gates are profile-independent:

- **Anchor sync.** Every moment records the narration words it is bound to, and
  `audit_sync` re-derives each moment's expected start from the word timings and
  compares. Record the worst drift in the report. A moment that is late against its own
  anchor words is the «حس سینک بودن» failure, and it is invisible in any still frame —
  a frame cannot tell you whether the voice has reached the sentence the type is
  showing.
- **Reading time.** The pacing gate charges each reveal step
  `0.45 + chars/11 + 0.3 × (blocks − 1)` seconds — fixation, reading, and one
  block-landing cost per additional block — against the step's own window. The shipped
  video measured 7-11 cps on every moment and passed its gate while the user could not
  read them, because the gate charged characters only and charged nothing for the
  entrance or for landing on the block. If a moment feels rushed at review, the number
  to compare is that step's charge, not the raw cps. Note that the profiles' entrance
  times differ (Film Type's is 0.56s from `film-type.json:139`) while the charged
  fixation constant does not.

Density targets for review: 7-9 moments per 60s, coverage ≤ 55%, every inter-moment gap
≥ 0.9s, and the first moment on screen within 0.6s — short-form feeds autoplay muted,
so an opening on silent footage is a blank first impression no matter what the
narration says a second later. The opening rule is about the *first moment's* timing,
not a separate hook: there is exactly one text layer, and the first moment of it is
the hook.

### Check the file

```bash
ffprobe -v error -show_entries stream=codec_type,width,height,channels \
        -show_entries format=duration -of default=noprint_wrappers=1 final.mp4
```

- Dimensions exactly 1080×1920 or 1920×1080.
- Duration within 1 second of planned.
- Audio streams present as authored. A silent video that was supposed to have
  narration is a broken promise, not a minor defect — and under the new gate, a
  narrated render with no music stream is a *gate failure*, not an artistic choice,
  unless `omitMusicReason` was set.

### Audio: verify the bed's levels, not just the presence of a stream

The ducking behaviour changed with the moment model, and the old measurement recipe
would now report a failure on a correct mix. The bed is **not** ducked against moments
any more — it sits at its base level throughout the narration, because ducking to
moments pumped the music down at instants where nobody was talking and held it up
during narration that had no moment on screen, an audible rhythm uncorrelated with the
voice. What the composition does now:

- narration present → bed at `musicBaseVolume` (0.6) throughout the voice,
- narration absent → bed flat at `musicFlatVolume` (0.5),
- fades at the head and tail of the bed, in both cases.

So the honest measurement is simpler and sterner: confirm the music stream exists in
the ffprobe output, and confirm the bed's *level* is as authored — sample a few windows
across the timeline and check the bed is present at a consistent level, with the
narration riding above it. If a ducking pattern appears — the level dipping and
recovering in rhythm with the moments — the composition is stale, not the mix; that is
a bug, not a style.

The old recipe (compare an RMS window where the voice speaks against one where it does
not, expecting the 0.6/0.36 ratio) measured a behaviour this pipeline no longer has.
Do not apply it; it will "fail" every correct render.

### What must never ship

Tofu boxes and reversed reading order. Both are immediately obvious to a Persian reader
and both make the video look broken rather than imperfect. On Legacy the measurements
above catch each one specifically. On Film Type tofu is still caught by any ink
measurement, but reversed order has no pixel check — so a Persian reader has to look at
every sampled frame before delivery.

### Do not reinvent the pixel checks

Each of these was implemented, measured against real renders, and abandoned. They are
listed because every one of them looks correct until it is tested. The traps are
properties of footage and of H.264, so they apply on both profiles even where the
quoted constant is Legacy.

| Approach | What defeated it |
|---|---|
| `mask = a.max(axis=2) > 200` for text | Selects bright footage. Sun on water scores higher than the glyphs |
| `min(channel) >= 225` for text | Neutral-and-bright rejects the accent `#FFC24B`, whose blue channel is 75 — i.e. every figure and every term on Legacy |
| Row-mean dip to find the darkened region | Over a gradient the row mean is dominated by the footage beside the type; the dip vanishes on a bright clip |
| Per-column darkening ratio | Fails wherever a camera move means the footage above a column is not what would have been under it |
| Ink-profile correlation for reading order | 0.86 margin in a clean rendering, 0.05-0.07 on the H.264 output — a confident answer from noise |
| Brightness threshold for the watermark | 35% of one search band came back as "watermark" |
| Local contrast for the watermark | Textured footage is bright pixels next to dark ones. False positive of 5003px against the mark's 792 |
| Row-gradient energy | Footage detail beat the mark 26:1 against 21:1 |
| Temporal invariance across frames | H.264 re-quantizes the static mark every frame, so it is not invariant in the output — and on Film Type the mark is not static at all |
| `measure_moment` on a gap frame | No scrim means `ink_mask` reads the footage: 31-99% "ink", and a confident scrim failure on a correctly empty frame |
| Zone-wide `measure_moment` over real footage | The zone is 803px tall; the scrim plateau for a short moment is ~300px. Rows in the falloff (96–168) pass ``SCRIM_CEILING=95`` and fabricate lines at the zone edges — the rendered fix scopes the verifier to the plateau (``stackHeightPx/2+28``) |
| Cross-shaped dilation to exclude the accent rim | A cross never covers a diagonal neighbour, so rim on every curve survives and reads as the unit — it failed a correct frame |
| Ink brightness to check a gap is empty | The zone the type would occupy is ungraded in a gap, so any brightness test is a test of the clip |
| Line-height arithmetic to predict the vertical gap | Estedad's slack depends on which glyphs are in the string; a numeral and «مسئله» differ by a third of an em, so no multiplier predicts both — only measuring the painted ink does |
| Centred text detection by column symmetry | A ragged RTL block is asymmetric by design; symmetry checks fire on every correctly set moment |
| Reusing the Legacy accent detector on a Film Type render | Film Type paints white ink, so the accent mask is empty and every accent-based verdict is about a colour that was never in the frame |

What works instead does not detect the text at all — it computes where the text must be
from the profile's own tokens, and uses a known alpha as the threshold that separates ink
from footage. Neither half depends on what the footage is doing. And where there is no
such alpha to threshold against — the gaps, the watermark, the whole Film Type surface —
the instrument changes rather than the threshold: colour separation for the Legacy accent,
an ablation render for the mark, band-to-band empty rows for the rhythm, and for Film Type
a comparison against the prepared geometry plus an actual painted-node or frame QA.

The Legacy versions are all in `lib/persian_verify.py`, with the reasoning at each
threshold; the Film Type verifier is `lib/persian_film_verify.py`.
`tests/lib/test_persian_verify.py` builds frames whose correct answer is known
by construction — synthetic bars where shape does not matter, real shaped Estedad where
it does — and `tests/contracts/test_persian_geometry_parity.py` pins every geometry and
scrim constant against `tokens.ts`, so the verifier cannot drift into measuring a zone
the type is not in or asserting a contrast the scrim no longer guarantees.

## If the render fails

`persian_compose` diagnoses the common failures in its error message. Beyond those:

| Symptom | Cause | Fix |
|---|---|---|
| Hangs, no frames | `delayRender` never resolved — font missing | Confirm `public/fonts/estedad/` exists and `--public-dir` was not overridden |
| "does not fit" throw | A moment's stack exceeds the height budget even at the smallest rung | Shorten it at the edit stage — split the moment, or cut the lead; the ladder bottoms out at its last rung (`HERO_LADDER_PX` in `tokens.ts` on Legacy, the profile ladders in `film-type.json` on Film Type) and the fitter throws instead of going below it |
| "No safe moving watermark schedule" | Film Type could not place the moving mark clear of every moment rect | An editorial fix: shorten or move a moment, or reduce the stack. Never widen the mark's clearance to make it fit |
| "Unsupported Film Type tokens" | The resolved profile hash is not in the renderer's version map | The new version needs explicit versioned renderer support; do not force the hash |
| Refused before rendering | A gate caught retired props, bad pacing, unanchored timings, or a missing music record | Read which rule the error names; fix the edit decisions, not the gate. Sync refusals → `retime_moments`; music refusals → the licence record |
| Black beats | A shot's `source` did not resolve | `persian_compose` raises `FileNotFoundError` rather than rendering it; fix the path in the edit decisions |
| Frame timeout | Large clip's first frame decode | Raise `timeout_ms` |

Do **not** resolve a render failure by switching runtime. If Remotion is genuinely
broken, raise a structured blocker. A HyperFrames swap produces fallback-font layout,
which looks plausible and is wrong — and it discards the measurement guarantees that
every check in this file depends on. The same holds for the profile: do not resolve a
Film Type refusal by falling back to Legacy.

## Render report contract

```json
{
  "output_path": "renders/final.mp4",
  "composition_id": "PersianFootageVertical",
  "format": "vertical",
  "render_runtime": "remotion",
  "duration_seconds": 60.0,
  "width": 1080,
  "height": 1920,
  "moment_count": 9,
  "text_coverage": 0.48,
  "subtitle_path": "renders/final.srt",
  "persian_text_verified": true,
  "verification_frames": ["renders/frames/moment-01.png"],
  "verification_notes": [
    "anchor: 27 lines, median 2.6px, worst 19.6px against a 32px tolerance",
    "contrast: 8.34:1 at worst, against a 5.6:1 floor",
    "gaps: accent coverage under 0.03% on every sampled gap; overruns of any kind are now detectable since every moment paints an accent hero",
    "rhythm: worst inter-band gap 41px against a designed 37px + tolerance — no half-leading leak",
    "sync: worst anchor drift 0.18s over 9 moments, against re-derived starts",
    "reading: every step's window ≥ 0.45+chars/11+0.3×(blocks−1); first moment on screen at 0.4s",
    "watermark: rows [318, 334], columns [331, 747], located by ablation diff",
    "intra-word glyph order is not verified in pixels"
  ],
  "attributions": ["Video by Jane Doe on Pexels", "…"],
  "music_track": {
    "name": "…",
    "license": {"name": "Pixabay Content License", "url": "…", "downloadedAt": "…"},
    "contentIdRisk": {"level": "low", "reason": "Pixabay Content License; third-party claims remain theoretically possible and are recorded, not excluded"}
  },
  "music_mixed": true
}
```

The `verification_notes` above are a **Legacy** example — anchor offsets, a 5.6:1 floor,
accent gap coverage and band rhythm are all Legacy quantities. A Film Type record reads
differently: the `verify_film_frames` rect/contrast/shadow/composite result against the
4.5:1 floor, the watermark slot schedule with each slot checked, the run's own warning
list, and an explicit `not_checked` for reading order, gap emptiness and stack rhythm.

`persian_text_verified` is set by **you**, never by a tool, and the bar depends on the
profile. On Legacy it means all five measurements agree:
`verify_frames(...)["passed"]` over every moment, `check_gap_is_empty` over every gap,
`check_moment_arrangement` over **every moment** with its own `roles` list,
`measure_stack_rhythm` over every moment with its own fitted lead size, and
`find_watermark` reporting `found` and not `clipped_at_edge`. On Film Type three of
those five cannot run, so a green run is not sufficient evidence: do not set it from
sampled checks. It needs `verify_film_frames` passing against the resolved props plus an
actual painted-node or frame review of every moment. `persian_compose` returns
it as `false` and cannot know otherwise — it renders, it does not look. Setting it true
without that evidence defeats the only check that catches the failures this
pipeline was built to prevent.

A green measurement run is not approval. Only the user's eyes approve a render, and a
run that reports `contrast-review-required` or subject-enforcement warnings is asking
for exactly that review rather than reporting a fault.

`verification_notes` should carry the numbers, not adjectives: the measured contrast,
the line counts, the watermark's measured rows or slots, the sync drift. "Looks good"
is not a verification record. Record what was **not** verified
in the same list — intra-word glyph order always, plus whatever the active profile has
no instrument for — because a reader who sees only passes will assume they were covered.

`text_coverage` is worth reading rather than skipping. It is the number that says whether
this is a typographic edit or a caption track, and it is invisible in the MP4 without
measuring it.

`music_track` must appear on any narrated delivery: the name, the licence record, and the
content-ID risk with its honest wording. The licence permits use; it cannot make
third-party claims impossible, and the record says so rather than promising safety no
automated check can verify.

`attributions` must cover every clip — both stock licences require it.
