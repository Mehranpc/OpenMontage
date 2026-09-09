## Film Type 2.11 current default

Read `docs/persian-film-type-2.11-patch.md` before the historical guidance below.
Approved diffuse shadow now defaults to strong for every new moment. Vertical
text and watermark use a conservative Reels safe area (14% top, 35% bottom,
8% left, 16% right), not a generic 9:16 margin. Reprepare all geometry; never move
measured rows manually. Review every moment with scripts/review_reels_safe_area.py
and the actual Instagram UI. Preserve face/action regions simultaneously; refusal
requires an editorial solution, not weaker margins. Existing complete pins stay
unchanged. 2.7 QA limitations still apply; safe-area success is not full approval.

## Film Type 2.7 migration override

For the 2.7 migration history, read `docs/persian-film-type-2.7-patch.md`
BEFORE the historical guidance below. That guide owns diffuse shadow, region
interpretation, diagnostic probes and version-aware QA. Pass resolved props to
verify_frames; never apply Legacy scrim-ceiling/anchor/orange-gap rules to Film
Type. Missing synchronized diagnostic evidence is not_checked, NOT a pass and
NOT evidence that the shadow failed. Do not set persian_text_verified from these
sampled checks. Review bright-background watermark separately. Keep old complete
pins unchanged; migrate only by fresh resolution and prepass.

# Executive Producer — Persian Footage Pipeline

## Film Type 2.6 — historical default path

At the time, every persian-footage run rendered Film Type 2.6 unless explicitly directed
elsewhere. Set `persian.design =
{"version":2,"profile":"film-type","seed":"<project-id>-film-type-01"}` (seed
auto-derived from the project id), then read
`skills/pipelines/persian-footage/film-type.md` before applying visual rules below.
That guide owns this profile's white ink, compact whole-run typography, placement,
conditional local contrast and two-line brand. Legacy orange/glow/rule, fixed-right
anchor, silhouette, static grade, dimming and accent-colour pixel recipes below do
not certify Film Type. Its prepared geometry requires actual painted-node/frame QA,
not the Legacy accent detector. All source, science, selective-moment, reading,
coverage, sync, narration/music, runtime, attribution and human gates still apply.
Absent design is REFUSED by persian_compose — no video renders Legacy by accident;
`quiet-editorial` stays available as an explicit option. The old Legacy render
remains reachable only through the explicit hidden opt-out
`{"version":2,"profile":"legacy"}` (emergencies only, never for new productions).
This routing is not Stage B completion, humanVisualApproval or C–E rollout. Do not
rewrite approved narration or facts to fit; request an editorial revision when
preparation refuses. See the guide for exact review steps.

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

Real stock footage carrying **designed typographic moments** — not a subtitled video.

- **Estedad** at real vendored weights (500/700/900) — never a synthesized bold.
- **7–9 moments in a 60-second video**, each a figure, a term, a claim, or a hook —
  the opening moment declares `kind: "hook"` and is the video's opening. The default
  hook style is claim+qualifier; a flat one-size style exists for an unsplittable
  single clause but currently cannot pass the silhouette gate. The selection rule,
  the style definitions, and every sizing value live in the hook section of
  `skills/pipelines/persian-footage/edit-director.md` and in
  `remotion-composer/src/persian/tokens.ts` — read them there, not here. Empty frame
  sits between moments. The narration carries the sentences; the type carries
  what the ear cannot hold.
- **One shared right edge.** Every line of every moment anchors to the same column,
  which is what makes seven to nine separate moments read as one designed video.
- **A gradient scrim**, not a panel, guaranteeing 5.6:1 contrast against any footage
  whatsoever — so no clip is ever too bright for the text.
- **A sidecar `.srt`** built from the narration's word timings. Real, toggleable,
  indexable subtitles instead of burned-in text.
- **A four-phase brand watermark** that announces itself once, then retreats.
- **Motion** from a defined grammar: four spring weights, arrival/exit verbs, and
  a living-hold that never transforms settled glyphs.

Vertical 1080×1920 by default. Landscape 1920×1080 for long-form YouTube; the same
components serve both, with type scales set per format rather than scaled from one.

### What it deliberately does not produce

A running transcript on screen. That was the first version and it was wrong: with a
caption under every sentence the viewer reads instead of watching, the footage becomes
wallpaper behind a text box, and the result is a reels-video with different clips. The
moment model exists to make the difference structural rather than a matter of taste —
`audit_moments` refuses a set whose text covers more than the ceiling in
`lib/persian_moments.py` (`MAX_TEXT_COVERAGE`), and
`persian_compose` refuses a `cues` key outright.

Karaoke emphasis went with it. It needed word-for-word on-screen text to highlight, and
there is none. Accessibility is better served by the sidecar `.srt` than it ever was by
burned-in words.

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
audio and produce the sidecar `.srt`.

Timing accuracy matters less than it once did: nothing on screen is locked to a word, so
a tenth of a second of drift is cosmetic rather than a visible bug.

The script stage **stops and hands the narration text to the user**. This is a real
handoff, not a checkpoint to click through — the pipeline cannot continue until the
audio comes back. Say so plainly and wait.

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
4. **Measure actual frames with `lib.persian_verify`.** `verify_frames` for ink, line
   count, the text column, zone occupancy, and contrast; `anchor_report` for drift
   across the whole render; `check_moment_arrangement` for RTL on a figure or term;
   `find_watermark` with a no-watermark reference render. A schema-valid
   `render_report` proves none of this, and neither does a hand-rolled brightness
   threshold — the compose-director records nine measured approaches that footage or
   the codec defeats.
5. **Check the subject quota.** First beat, last beat, and ≥40% of footage beats show
   the video's declared subject. Read the manifest's `selection_reason` lines: if they
   say "best match" rather than what is in frame, the quota was not actually checked.
6. **Count typographic beats.** Over the declared budget means footage sourcing
   gave up too early.
7. **Check attribution.** Both Pexels and Pixabay require it; a clip that cannot be
   attributed should not have shipped.
8. **Confirm `persian_text_verified` was earned.** It is `false` out of
   `persian_compose` and may only be flipped after `verify_frames(...)["passed"]` and an
   arrangement check. `verification_notes` should carry numbers, not adjectives.
