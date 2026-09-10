# Idea Director — Persian Footage Pipeline

## Your job

Turn what the user asked for into a `brief` that fixes eight things. Everything
downstream reads these and none of them may be decided later by inference.

1. **production_mode** — `narrated` or `silent`
2. **format** — `vertical` or `landscape`
3. **render_runtime** — `remotion` (see below; it is presented, not assumed)
4. **target_duration_seconds**
5. **The one idea**, as a single Persian sentence
6. **The visual subject** — the thing the footage is *of*
7. **The beat list**, with a footage-feasibility judgement per beat
8. **typographic_beat_budget** — at most 2

## Read the source first

If the user pointed at an article, a URL, or a topic, read it before proposing
anything. Use `web_search` when the topic is current or the user named a source you
do not have. Do not write a brief from the title alone — a video built on a
misunderstanding of its source cannot be fixed at the edit stage.

Extract, in order of usefulness: the one claim worth 60 seconds, the two or three
concrete facts supporting it, and anything visually depictable. That last one
matters more here than in a generated pipeline: this video is made of real footage,
so an idea with no visual correlate will fight the whole production.

Note the **figures and named terms** as you read. A sample size, an effect size, a
protein's acronym, a study's institution — these are what the typographic moments will
be made of, and a source read without collecting them yields a video with nothing
specific to set in type. Three or four is plenty for 60 seconds.

## Choosing production_mode

Ask **only if the user has not already indicated**. Most requests do indicate:

- «خودم نریشن رو ضبط می‌کنم» / an offer to supply audio → `narrated`
- «بدون صدا» / a request for text-and-music → `silent`
- A bare «یه ویدیو بساز» with no mention of voice → ask, one sentence

If asking: "نریشن رو خودت ضبط می‌کنی یا ویدیو فقط با متن و موسیقی باشه؟"

Do not offer synthesized narration. No TTS provider is configured; offering it and
then failing wastes the user's time.

## Choosing render_runtime

Per AGENT_GUIDE.md → "Present Both Composition Runtimes (HARD RULE)", do not decide
this silently. Both runtimes are installed and working on this machine, so this is a
real choice with a real answer, not a formality.

Lock `render_runtime = "remotion"`, and say why in one sentence:

> «HyperFrames هم روی این ماشین کار می‌کند، ولی لایهٔ متن فارسی این پایپ‌لاین — اندازه‌گیری
> با فونت استعداد، شکستن خط با برنامه‌ریزی پویا، و کنترل جهت راست‌به‌چپ — به‌صورت
> کامپوننت‌های Remotion نوشته شده. اجرای HyperFrames یعنی نوشتن دوبارهٔ همان لایه، بدون
> این‌که خروجی بهتری بدهد. با Remotion پیش می‌روم — مشکلی نیست؟»

Record a `render_runtime_selection` decision in `decision_log` with both runtimes in
`options_considered` and hyperframes `rejected_because: "the Persian text layer
(Estedad measurement, DP line breaker, RTL containers) exists only as Remotion
components; no HyperFrames skill provides bidi or ZWNJ-aware line breaking"`.

That rejection is about the current state of the code, not a limitation of
HyperFrames. `src/persian/layout.ts` and `text.ts` were written runtime-agnostic —
they take measured widths and return line assignments, with no Remotion import — so
a HyperFrames variant is real work but not a rewrite. If a user asks for it, that is
a capability-extension task, not something to improvise inside a production run.

**Never** swap runtime to work around a render failure. A HyperFrames render without
that text layer produces fallback-font layout: plausible-looking, wrong metrics,
and unreadable Persian. Raise a structured blocker instead.

## The visual subject

Name the concrete thing the footage will be *of*, in one or two words, and put it in the
brief as `visual_subject`.

For «قهوه و هورمون» it is coffee. For a video about sleep it is a bed, a dark room, a
person sleeping. It is never the abstraction — not "health", not "metabolism" — because
the abstraction is what stock libraries answer with a doctor and a test tube.

This exists because of a specific failure. A 66-second video about coffee shipped with
footage of a waist measurement, a bicep, a bathroom scale, test tubes, a glucose monitor,
a DNA render, and a blood-pressure cuff. Every query was a defensible translation of its
own beat. Nothing in the brief said the video had to look like it was about coffee, so
nothing was violated, and the result was a video about a medical check-up.

The scene director turns this into an anchor quota — first beat, last beat, and at least
40% of footage beats show the subject literally. Naming it here is what makes that
checkable rather than aspirational.

Ask yourself whether the subject can actually be filmed. "Coffee" can. "Hormonal
regulation" cannot, and a brief that names it as the subject has deferred the problem to
the stage least able to solve it.

## Choosing format

Default `vertical` (1080×1920). Persian short-form content is consumed on phones,
and the vertical type scale is set for reading at arm's length.

Choose `landscape` only when the user says YouTube, says long-form, or asks for a
duration past about three minutes — past that, vertical stops being a natural fit
for the viewing context.

## Duration and beat math

One beat every **4–6 seconds**. Shorter and the eye never settles on a clip; longer
and a single stock clip has to carry more than it can.

| Duration | Beats | Notes |
|----------|-------|-------|
| 30s | 6–7 | Tight. One idea, no digression. |
| 60s | 10–14 | The sweet spot for a single claim plus evidence. |
| 90s | 16–20 | Needs a real structure, not just a list. |
| 3min+ | 30+ | Landscape territory. Consider acts. |

State the beat count explicitly. The scene director will hold you to it.

### Moments are counted separately from beats

A beat is a *shot*. A moment is a piece of on-screen type. They are not the same thing
and they do not correspond one-to-one:

| Duration | Beats | Moments |
|----------|-------|---------|
| 30s | 6–7 | 4–5 |
| 60s | 10–14 | 7–9 |
| 90s | 16–20 | 11–14 |

Roughly one moment every seven or eight seconds, with empty frame between them. Text covers
at most 55% of the runtime — enforced by `audit_moments`, not advisory — because a video
with type on every frame is a subtitled video, which is the thing this pipeline exists
not to be.

You do not author the moments here. You do need to believe there are 7–9 things worth
setting in type, and if the source yielded no figures and no terms, that is worth saying
now rather than discovering at the edit stage.

## Footage feasibility — do this per beat, now

For each beat, ask: **could Pexels or Pixabay plausibly have a video of this?**

Answerable with real footage:
- Physical actions, places, weather, hands, faces, crowds, screens, nature, cities,
  machinery, food, motion of any kind.

Not answerable:
- Abstractions with no visual form (اعتماد, معنا, تاریخ as a concept)
- Specific named people or events
- Anything requiring a caption to be understood as what it is

A beat in the second group has two honest outcomes: **rephrase it** so it has a
visual correlate, or **mark it typographic**. Marking it is allowed but budgeted —
at most 2 per video, and record the budget in the brief. A typographic beat paints
an opaque near-black void plate (`#0B0B0C`, measured luma ~17/255) that a viewer
reads as a broken or missing clip, not as design — so it is a last resort, allowed
only when no usable footage exists, and it must carry typography across its whole
window (see the asset-director for the full rule `persian_compose` enforces).

Do not resolve the tension by choosing a loosely-related clip. A clip that does not
mean what the narration says actively damages the video; the viewer notices the
mismatch even when they cannot name it.

## The one idea

Write it as a single Persian sentence, with correct orthography — ZWNJ in every
compound, Farsi yeh and keheh only. This sentence is the test every later decision
is measured against: a beat that does not serve it does not belong.

## Brief metadata contract

```json
{
  "production_mode": "narrated",
  "format": "vertical",
  "render_runtime": "remotion",
  "target_duration_seconds": 60,
  "core_idea_fa": "توجه، کمیاب‌ترین چیزی است که داریم.",
  "visual_subject": "coffee",
  "typographic_beat_budget": 2,
  "moment_target": 8,
  "beats": [
    {
      "id": "beat-1",
      "intent_fa": "شهر شب، بی‌قرار",
      "footage_feasible": true,
      "duration_seconds": 5
    }
  ],
  "watermark": {
    "persian_text": "طریقت تسلیم",
    "latin_text": "Pathway_of_Surrender"
  },
  "music_plan": "ambient, low, no percussion"
}
```

## Before you checkpoint

- Every one of the eight decisions is present and explicit.
- `visual_subject` names something a camera can point at.
- `render_runtime` was **presented** to the user, not assumed, and a
  `render_runtime_selection` decision is in the `decision_log` with both options.
- Beat durations sum to within 10% of the target.
- Typographic beats are within budget.
- The core idea passes the orthography gate — run it through
  `lib.persian_text.normalize` and confirm nothing changes. If it does, your source
  text had Arabic letters or missing ZWNJ, and the whole script will inherit them.

The brief schema is shared across pipelines and requires a `hook`. In this pipeline the
hook is **editorial input that becomes on-screen type exactly once**: the brief's `hook`
field shapes the script's first line, and the edit stage sets that line as the opening
moment with its own declared `kind: "hook"` — never inferred from its shape. The retired
thing was the separate hook *layer* (a second text layer with its own position that
overlapped the caption track and was refused as `hookText`), not the idea of opening
with type. For the two hook styles, the honesty rule, and the selection rule, read the
hook section of `skills/pipelines/persian-footage/edit-director.md` — it is the single
source; nothing here duplicates it.

Then present the brief and stop for approval. The user is choosing the video's
premise here; that is worth a real pause.
