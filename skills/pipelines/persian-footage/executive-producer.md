# Executive Producer — Persian Footage Pipeline

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

Real stock footage under Persian text, with:

- **Estedad** at real vendored weights (500/700/900) — never a synthesized bold.
- **Glass subtitle panels** that establish their own contrast, so readability does
  not depend on how bright the clip behind them happens to be.
- **Karaoke emphasis** locked to narration word timings when narration exists.
- **A four-phase brand watermark** that announces itself once, then retreats.
- **Motion** from a defined grammar: four spring weights, arrival/exit verbs, and
  a living-hold that never transforms settled glyphs.

Vertical 1080×1920 by default. Landscape 1920×1080 for long-form YouTube; the same
components serve both, with type scales set per format rather than scaled from one.

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
| Overflow / shrink | Text past the panel, or mysteriously small | Canvas measurement + fit ladder |
| Too fast | Cue gone before it is read | 21 visible chars/second ceiling |

### 2. Beauty (زیبایی)

Beauty here is not decoration; it is the absence of specific ugliness:

- **No frozen frames.** A settled beat still breathes — but only through the room
  (drifting light, background plate), never by transforming type.
- **No glyph shimmer.** Settled text changes only in glow alpha and brightness. A
  sub-pixel transform on Persian's thin horizontal joins produces visible edge
  buzz.
- **No mismatched footage.** A clip that contradicts the narration is worse than no
  clip. Beats with no honest footage become typographic — at most two per video.
- **No stock-montage look.** A consistent static grade pulls unrelated clips
  toward one look.

## Stages

| Stage | Director skill | Produces |
|-------|---------------|----------|
| `idea` | `idea-director.md` | brief — mode, format, duration, beat count |
| `script` | `script-director.md` | script — Persian text, gate-passed |
| `scene_plan` | `scene-director.md` | scene_plan — beats with English queries |
| `assets` | `asset-director.md` | asset_manifest — video clips + word timings |
| `edit` | `edit-director.md` | edit_decisions — cues, shots, watermark |
| `compose` | `compose-director.md` | render_report — the MP4 |

Read the stage director skill before working in that stage. Not optional: each one
carries constraints that are not derivable from the manifest.

## Production modes

Chosen at `idea` and recorded in the brief. The choice changes what later stages do,
so it must not be inferred later.

### `narrated` (default)

The user supplies Persian narration audio. Word timings come from transcribing that
audio, so karaoke emphasis lands on the syllable actually spoken.

The script stage **stops and hands the narration text to the user**. This is a real
handoff, not a checkpoint to click through — the pipeline cannot continue until the
audio comes back. Say so plainly and wait.

### `silent`

No narration. Cue timings derive from reading speed; music carries the pace. Choose
this when the user wants a result without recording, or before narration exists.

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
2. **Run the cue audit.** `lib.persian_cues.audit_cues` — reading speed, minimum
   duration, overlap. An overlapping pair renders two glass panels on one frame.
3. **Measure actual frames with `lib.persian_verify`.** `verify_frames` for ink, line
   count, panel envelope, centring, and contrast; `check_reading_order` for RTL;
   `find_watermark` with a no-watermark reference render. A schema-valid
   `render_report` proves none of this, and neither does a hand-rolled brightness
   threshold — the compose-director records six measured approaches that footage
   defeats.
4. **Count typographic beats.** Over the declared budget means footage sourcing
   gave up too early.
5. **Check attribution.** Both Pexels and Pixabay require it; a clip that cannot be
   attributed should not have shipped.
6. **Confirm `persian_text_verified` was earned.** It is `false` out of
   `persian_compose` and may only be flipped after `verify_frames(...)["passed"]` and a
   reading-order check. `verification_notes` should carry numbers, not adjectives.
