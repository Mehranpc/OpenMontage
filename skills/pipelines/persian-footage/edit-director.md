# Edit Director — Persian Footage Pipeline

## Explicit Film Type routing (opt-in only)

When—and only when—the user explicitly selects `persian.design =
{"version":2,"profile":"film-type","seed":"project-specific"}`, read
`skills/pipelines/persian-footage/film-type.md` before applying visual rules below.
That guide owns this profile's white ink, compact whole-run typography, placement,
conditional local contrast and two-line brand. Legacy orange/glow/rule, fixed-right
anchor, silhouette, static grade, dimming and accent-colour pixel recipes below do
not certify Film Type. Its prepared geometry requires actual painted-node/frame QA,
not the Legacy accent detector. All source, science, selective-moment, reading,
coverage, sync, narration/music, runtime, attribution and human gates still apply.
Absent design remains Legacy; `quiet-editorial` stays on its existing path. This
routing is not Stage B completion, humanVisualApproval, a default switch or C–E
rollout. Do not rewrite approved narration or facts to fit; request an editorial
revision when preparation refuses. See the guide for exact opt-in review steps.

## Your job

Produce `edit_decisions` with a `persian` block: the exact props the composition
renders. This is where footage, script, and timings become one timeline.

The text half of that job is **not** transcribing the narration. It is choosing the
few things worth setting in type, writing each of them as **one grammatical Persian
phrase**, and binding every one of them to the moment the voice says it.

## Moments, not captions

The composition paints an ordered list of `moments`. There is no running subtitle and
no on-screen transcript — the narration carries the words, and the type carries what
the ear cannot hold: a number, a term, a claim worth stopping on.

This is the whole reason the pipeline exists. A Persian video whose every sentence is
also on screen is a reels-video with different footage: the viewer reads instead of
watching, the footage becomes wallpaper behind a text box, and the design has nothing
to do because every frame is the same frame.

So the rule is **selective, not continuous**:

- **7–9 moments in a 60-second video.** Roughly one every seven or eight seconds.
- **Text covers at most 55% of the runtime.** Enforced, not advised —
  `audit_moments` refuses a set above it, because that is the one rule a
  well-behaved caption track cannot satisfy.
- **At least 0.9s of empty frame between moments.** Also enforced. Two moments a
  quarter-second apart are a caption track whatever they are called, and the gap is
  what makes the footage readable as footage.

The old density target was 12–15 per minute. That target is now impossible, and this
is worth internalising: a moment is a **phrase** with a reading floor of 2.4s plus
fixation time, and 13 such moments in 64s is 55% coverage with **zero** seconds left
for the gap. The remedy is not thinner moments — it is fewer, richer ones. If you
find yourself with a moment per sentence, you are writing captions. Delete half of
them and make the survivors say whole sentences.

### Accessibility is not the reason to burn text in

`persian_compose` writes a sidecar `.srt` from the narration's word timings — real
subtitles, in a real format, that a viewer can turn on and a platform can index. That
is strictly better for accessibility than burned-in text, which cannot be turned off,
cannot be translated, and cannot be read by anything but a human eye.

Pass `audio.wordTimings` and the file appears beside the MP4. You do not build cues
by hand and you do not put them in the props; `persian_compose` refuses a `cues` key
outright.

## The moment model: one phrase, one emphasis

A moment is **one grammatical Persian phrase with one emphasised span inside it**. It
is carried by `segments`, an ordered list where **the array order is the reading
order, top to bottom**. The renderer paints in that order with no sorting of its own.

```json
{
  "id": "moment-2",
  "kind": "figure",
  "startSeconds": 6.4,
  "endSeconds": 10.9,
  "anchorText": "بیست و دو هزار و ششصد و شصت و چهار نفر",
  "segments": [
    { "role": "lead", "text": "مطالعهٔ دانشگاه اولوی فنلاند روی" },
    { "role": "hero", "text": "۲۲۶۴ نفر" }
  ]
}
```

Read the segments top to bottom and they read as the sentence: «مطالعهٔ دانشگاه
اولوی فنلاند روی ۲۲۶۴ نفر». This example is not mine to invent — it is the user's
own answer to the question "what should this frame have said", given after seeing the
frame that said less. The word order matters and the array preserves it exactly.

### Why this replaced the slot model — the frame that was rejected

The old model had a hero field, a `unit` field beside the number, a `label` below,
a `kicker` above. Each slot had its own size, its own colour, its own alignment. For
the same study it produced:

- «۲۲۶۴» set at 260px, right-anchored;
- «نفر» at 44px, floating at the numeral's baseline, several hundred pixels to its
  left — because the unit was *its own field* and its own field got its own position;
- «دانشگاه اولو، فنلاند» at 44px on a third line.

Three type sizes, three left edges, and no sentence anywhere. Nothing on screen said
a study was being described. The viewer's verdict: «معلوم نیست در مورد چیه! در مورد
کیه!» — *what is this about? about whom?* The information was all present and the
grammar was missing, which is not a styling defect: it is a layout asserting
relationships the language never stated.

Every rule below exists because of that frame or one like it.

### The four roles

| Role | What it is | Ink | Size |
| --- | --- | --- | --- |
| `lead` | the part of the phrase that sets up the emphasis | primary | `LEAD_RATIO` × hero (see `tokens.ts`) |
| `hero` | **the** emphasis — the thing the frame exists for | accent | the ladder |
| `tail` | the part that completes the phrase *after* the hero | primary | `LEAD_RATIO` × hero (see `tokens.ts`) |
| `source` | a citation appended to the phrase | secondary | `SOURCE_RATIO` × lead (see `tokens.ts`) |

- `lead` is where Persian usually starts: «مطالعهٔ … روی», «میانگین سنی
  شرکت‌کنندگان:». The user's complaint about the age frame — «حتی بدتره» — was that
  it showed a number with nothing saying what it counted. The fix is a lead that
  names it, not a label under it.
- `hero` carries the accent colour and the largest type. The user loved the large
  orange hero; keep it. **Exactly one hero per reveal step** — zero is a caption,
  two is an emphasis competing with itself.
- `tail` exists because Persian sometimes finishes after the fact: «… را سه برابر
  می‌کند». Forcing that into a `lead` would place it above the thing it follows.
- `source` is not part of the phrase; it is a citation appended to it. At most one,
  and it must be the last segment.

### The unit lives inside the hero

«۲۲۶۴ نفر» is the hero, as one text. Never split a spoken quantity across two type
sizes — the floating «نفر» is the single most-rejected detail of the old render, and
it was produced by a *field* whose only purpose was to sit somewhere else. If the
quantity is «۴۶ سال», the hero is «۴۶ سال».

### `kind` is editorial metadata, not an arrangement

`kind` — `figure`, `term`, `statement`, `hook` — still exists. It no longer decides how the
frame is arranged; the segments do. It records what the moment *is* so the audits can
reason about variety (a video of nothing but statements is its numbers being set as
running text) and so a reviewer can see the edit's judgement. Choose it honestly; do
not expect it to change anything about layout — with one exception: `hook` switches
on the hook's scoped tokens (its ladder offset, its qualifier size and weight, its
gap, its two-beat arrival, and the silhouette gate), because an opening frame that
had to look like its content to be recognised would not be declared at all.

### Character ceilings, per role

Ceilings are per segment, enforced by `audit_moments` — the values live in
`lib/persian_moments.py` (`MAX_HERO_CHARS`, `MAX_SUPPORT_CHARS`,
`MAX_SOURCE_CHARS`, `MAX_FLAT_HERO_CHARS`), which is their single source of truth:

- `hero` ≤ the hero ceiling.
- `lead` / `tail` ≤ the support ceiling.
- `source` ≤ the source ceiling.
- A flat-hook hero (one hero carrying `accentWords`, a whole sentence at one size)
  ≤ the flat-hero ceiling — a longer sentence is a paragraph, not a hook.

These are generous enough for a full phrase and tight enough that the type ladder
(see below) never has to shrink the emphasis into invisibility. A statement that
needs more than the hero ceiling for its hero is two moments, or a poster line that has
not been cut yet.

### Hook refusals

Beyond the per-role ceilings, a hook is refused unless it matches exactly one of the
two styles — claim+qualifier (a hero plus a tail, no `accentWords`) or flat display
(a single hero carrying `accentWords`): the predicates are `is_claim_qualifier_hook`
and `is_flat_display_hook` in `lib/persian_moments.py`, and a declared `hook` matching
neither is refused rather than fitted as an ordinary moment. A hook carries no `source`
— it is the opening frame, not the evidence. And `accentWords` and the hook kind appear
on the opening moment only: either past the first moment is refused.

### Sizes are derived, not chosen

You do not set sizes and neither does the `kind`. The renderer walks `HERO_LADDER_PX`
from the top and takes the **largest rung at which the whole stack fits** its width
budget and its height budget. The lead derives from the hero via `computeLeadPx`,
the source from the lead, the gap from the lead — read the ratios and the clamps in
`remotion-composer/src/persian/tokens.ts`, which is the single source of truth for
every number in this section. A short micro hero additionally receives the presence
lift (`SHORT_HERO_*` in the same file): it walks up while the stack stays narrow, so
«قهوه» carries its weight beside «۲۲۶۴ نفر» at the same emphasis.

Consequences worth planning around:

- A short hero («۲۲۶۴ نفر») lands high on the ladder — huge, orange, dominant.
- A long hero («چربی کمتر، عضلهٔ بیشتر») lands lower, with its lead at a
  *proportion* of it, so the two always read as one phrase with an emphasis rather
  than as a heading over a subheading.
- The old 38px orange kicker under an 80px claim — «سایز خط اول و دوم تناسب نداره.
  خط نارنجی بیش از حد کوچیکه!» — cannot recur, because the ratio is now the
  constant and the absolute size is measured.

### Builds: accumulate, don't replace

A moment can reveal in steps. Give a later segment `revealAfterSeconds` and it
**joins** the phrase at that time: earlier segments stay on screen and dim to 0.55
opacity, the new one arrives at full strength.

```json
{
  "id": "moment-5",
  "kind": "figure",
  "startSeconds": 18.0,
  "endSeconds": 24.4,
  "segments": [
    { "role": "lead", "text": "پیمایش ۱۲ ساله نشان داد:" },
    { "role": "hero", "text": "خطر دیابت ۲۳٪ کمتر" },
    { "role": "lead", "text": "در همان میانگین سنی", "revealAfterSeconds": 3.2 },
    { "role": "hero", "text": "۴۶ سال", "revealAfterSeconds": 3.2 }
  ]
}
```

This is the user's explicit request: two facts that belong to one thought should
**accumulate** rather than replace each other — «گاهی باید متن‌ها به جای رد شدن
جمع بشن». Use it when the second fact only makes sense with the first still on
screen. Do not use it for everything; a build is a beat, and a video of constant
beats has no rhythm.

One moment, multiple reveals — so the 0.9s gap floor does not apply *between steps*,
only between moments. Each reveal step still needs its own reading time (below), and
the audit charges it separately.

### Retired keys are refused, not deprecated

`text`, `label`, `kicker`, `unit`, `highlight` on a moment: refused outright, with an
error that explains the slot model they imply and why it went. Same for `cues` and
`hookText` at the block level. If an old artifact is your starting point, rewrite the
moments; do not try to smuggle old fields through.

## Where the text goes, and why you do not choose

Every moment is anchored to the **same right edge** and sits in the same vertical band
across the middle of the frame. Not centred, not per-moment.

That is a design decision made in `tokens.ts` and it is not yours to vary: a shared
spine is what makes a handful of separate moments read as one designed video rather
than a stack of text overlays. `lib/persian_verify.py` checks it per line and fails a
render whose type drifted off the anchor.

Contrast comes from a gradient scrim behind the band — no panel, no box. It
guarantees 5.6:1 against any footage whatsoever, so you never need to reject a clip
for being too bright, or lighten text to compensate.

The **vertical rhythm** — the size of the gap between one block and the next — is the
compose stage's concern (measured ink, not line boxes; the 133px hole in the old
render was leading leak, not a gap anyone chose). What is yours: how many blocks a
moment has, and whether they say something worth that much height.

## Pacing: give each moment time to be read

The reading model is charged **per reveal step**:

```
0.45s fixation  +  visible_chars / 11 cps  +  (blocks − 1) × 0.3s
```

- The **fixation** term exists because the old model charged only characters, and a
  2.0s moment declared "adequate" for 22 characters gave the viewer about 1.5s once
  the entrance animation was subtracted. The complaint — «متن‌ها گاهی بیش از حد
  سریع رد میشن و اجازه خوندن به مخاطب نمی‌دن» — is that number, felt.
- The **blocks** term is the eye landing on each block of the phrase.
- `source` characters count at half weight — a citation in the smallest type is
  skimmed, not read.
- `MIN_SECONDS` is 2.4 and `MAX_SECONDS` is 9. Under 2.4 is a flash; over 9 and the
  frame stalls. Builds may legitimately use the upper range — they carry several
  reads.

`11 cps` is roughly half the 21 the sidecar subtitles allow, because a moment is
read *while the footage plays*, in a glance, against motion.

The arithmetic includes the whole phrase, not just the hero. A figure with a long
lead needs longer than its five digits suggest — `min_read_seconds` on the built
moment tells you how much.

## Opening: the first moment is the hook

The first moment must start within **0.6s** of frame zero.

Feeds autoplay muted. For the first second or two, the narration does not exist —
and a video that opens on silent, textless footage gives a scrolling thumb nothing:
«ویدویی که شروعش فوتیج خالیه این خطر رو داره که توسط کاربر رد بشه». The first
moment *is* the opening; there is deliberately no separate hook layer, because the
hook layer was deleted for being a **second text layer** that overlapped the caption
track — not for opening with type. One layer, and its first frame
says something.

Moment-1 MAY paraphrase the opening narration as a hook — the one moment permitted
to restate rather than transcribe. The paraphrase still names its anchor: `anchorText`
carries the opening words as spoken, and the sync audit applies unchanged. Every claim
in the hook appears again as said or shown later in the video: «این اشتباه می‌تونه
فواید قهوه رو نابود کنه!» was rejected because the video never names such a mistake —
a hook that invents jeopardy the narration never earns. Curiosity, warning, or challenge
techniques are welcome — «می‌دونی قهوه با هورمون‌هات چی‌کار می‌کنه؟» teases what the
video itself answers — and the test is always whether the video makes the claim, not how
loud the hook asks.

A hook is declared with its own `kind: "hook"` — never inferred from its shape.
The default style is claim + qualifier: the `hero` carries the claim in accent
and the `tail` completes it in primary ink, set larger relative to the hero than
an ordinary lead (the ratio lives in `tokens.ts`, scoped to hooks so ordinary
moments keep their ceiling). Both lines share the weight class, arrive in two
beats — claim, then qualifier — and read as a step rather than a block: the
silhouette gate in `persian_compose` refuses a hook whose lines are nearly equal
in width, and `tokens.ts` documents the band it enforces.

The flat one-size style remains for a single-clause sentence where any split is
arbitrary — such as the previously rejected «می‌دونی قهوه با هورمون‌هات
چی‌کار می‌کنه؟», where no grammatical split exists: one hero-only segment at one
size in primary ink with `accentWords` naming one or two keywords (`tokens.ts`
documents the treatment; the sized lead/hero/tail model stays for every other
moment). Note honestly that the flat style cannot currently pass the silhouette
gate — its line breaker balances lines, and balanced lines are a rectangle by
construction — so a flat hook renders but is refused at compose time until it
gets a hook-specific break objective. A flat hook is typeset as a display block
rather than as an emphasis span: it may run to more lines and breathes on looser
leading than an emphasis span does, with the values living in `tokens.ts`.

The selection rule is grammatical and measured, not taste: prefer
claim+qualifier when a legal, balanced split into a nominal head and a
prepositional tail exists; keep the flat style for the sentence no split serves.
Give
the hook room to be read
by extending `endSeconds` into the head gap; the 0.9s gap floor and the 55% coverage
ceiling still hold.

Practically: put the strongest claim or figure the script opens with into
`moment-1`, anchored to the first phrase of the narration, starting at 0.2–0.6s.
The entrance animation takes ~0.45s; a moment that starts after 0.6s has already
missed the decision window.

## Anchoring: timings come from the voice

In narrated mode, **every moment carries `anchorText`** — the narration words it
belongs to, written as they are spoken.

- `anchorText` is the **spoken** form, not the on-screen form. If the type says
  «۲۲۶۴ نفر», the anchor is «بیست و دو هزار و ششصد و شصت و چهار» — because
  `lib/persian_sync.py` matches it against the transcription's word timings, and the
  transcription holds the spoken words.
- The moment should start slightly *before* its anchor words: the type lands, then
  the voice confirms it. The sync audit tolerates 0.5s of drift between your
  authored start and the derived one.

### The rescaled-timings disaster, in numbers

The first render of the current test video was built from a *different* narration
file, its timings rescaled by the duration ratio (66.08s → 63.86s, factor 0.966404)
instead of re-derived from the new voice. Every moment kept the old edit's shape and
drifted against the new speech — moment-01 appeared **+3.41s early**, moment-13
+1.68s early, moment-06 −1.07s late. The user's verdict: «خیلی وقت‌ها هم حس سینک
بودن صدا با نمایش رو نمی‌ده اصلا. نمی‌دونم باگش کجاست.»

The audit now refuses exactly that: an anchor not found in the word timings, or an
authored start more than 0.5s from the derived one, does not pass.

### When the audit refuses

Use `retime_moments` from `lib/persian_sync.py`. It re-derives every moment's start
and end from the word timings — the honest remedy. **Never rescale by a duration
ratio.** A ratio preserves the shape of the old edit and preserves nothing about
the new speech; it is the one operation that produced a technically-plausible,
fully-wrong timeline, which is why it is named here in full.

```python
from lib.persian_sync import TimedWord, audit_sync, retime_moments

words = TimedWord.from_dicts(audio["wordTimings"])
audit = audit_sync(moments, words)
assert not audit.problems, audit.problems   # anchor missing / not found / drifting
moments = retime_moments(moments, words)     # re-derive from the voice
```

## Music is required in narrated mode

A narrated video ships **with a music bed**. Delivering one silent and asking
afterwards «می‌خوای موزیک هم بهش اضافه کنم؟» is the exact failure the user named:
the question belongs before the render, not after it.

The `audio` block carries `music` plus a `musicTrack` record:

```json
{
  "audio": {
    "narration": "assets/audio/voiceover.mp3",
    "music": "assets/music/track.mp3",
    "wordTimings": [ … ],
    "musicTrack": {
      "path": "assets/music/track.mp3",
      "source": "pixabay",
      "license": { "name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/", "downloadedAt": "2026-09-02" },
      "attribution": "—",
      "contentIdRisk": { "level": "low", "reason": "Pixabay Content License permits commercial use; no attribution required" }
    }
  }
}
```

`lib/persian_music.py` audits the record:

- `contentIdRisk.level` is `low`, `unknown`, or `high`. **`high` is refused.**
- `low` must cite a known licence name — Pixabay's Content License (the
  `pixabay_music` tool needs no API key) is the default path and is documented as
  free for commercial use, no attribution required, no standalone redistribution.
- `unknown` passes only with `acknowledgeUnknownMusicRisk: true` in the block — a
  human-visibility stamp, not a rubber stamp.
- Deliberate silence is legitimate but must say why: `omitMusicReason: "…"`.

Record the licence fields even when the tool reports them as permissive. Third-party
Content-ID claims on Instagram cannot be ruled out by any automated check — the
honest output is a provenance record and a stated risk level, not a promise of
safety. That is what the audit enforces: not «guaranteed safe» but «known source,
known licence, known date».

## Shots

One shot per beat, in timeline order, contiguous. A gap between shots renders as
black; an overlap renders as whichever `<Sequence>` is later in the array, which is
not a decision you want made by array order.

```json
{
  "id": "shot-1",
  "source": "assets/clips/pexels_1234567.mp4",
  "startSeconds": 0.0,
  "endSeconds": 5.0,
  "sourceInSeconds": 2.0,
  "camera": "push-in",
  "attribution": "Video by Jane Doe on Pexels"
}
```

`sourceInSeconds` picks the in-point inside the clip. Choose it by looking: stock
clips frequently open on a fade, a slate, or a half-second of the wrong framing.
Starting at 0 is a default, not a decision.

`attribution` is required — `persian_compose` refuses to render a shot without one.

### Place moments against the footage, not against the script

A moment lands on a shot. Prefer a shot whose subject is low or left in frame, or
whose motion has settled — the scrim guarantees legibility, but a moment over a
close-up face still competes with it for attention.

The strongest placement is a moment that *arrives with a cut*: the shot changes and
the figure appears on the new frame. Placing one mid-shot works; placing one two
frames before a cut does not, because it is gone before it is read.

## The `persian` block

```json
{
  "render_runtime": "remotion",
  "composition_mode": "templated",
  "renderer_family": "persian-footage",
  "persian": {
    "format": "vertical",
    "durationSeconds": 66.1,
    "shots": [ … ],
    "moments": [ … ],
    "typographicBeats": [ { "id": "beat-7", "startSeconds": 30.0, "endSeconds": 34.0 } ],
    "audio": {
      "narration": "assets/audio/voiceover.mp3",
      "music": "assets/music/track.mp3",
      "wordTimings": [ { "word": "قهوه", "start": 0.2, "end": 0.6 } ],
      "musicTrack": { … }
    },
    "watermark": { "persianText": "طریقت تسلیم", "latinText": "@Pathway_of_Surrender" }
  }
}
```

`render_runtime` must be `"remotion"`. `persian_compose` refuses anything else, and
that refusal is deliberate: the composition depends on `FontFace` and canvas
measurement, neither of which exists on the other paths.

`wordTimings` drives two things now — the sidecar `.srt` **and** the sync audit /
`retime_moments`. In narrated mode it is required, not optional. Omit it only in
silent mode, where there is no voice to anchor to and no subtitle file to write.

Every moment carries its declared `kind` (`figure`, `term`, `statement`, `hook`).
`fitMoment(segments, format, kind)` in `remotion-composer/src/persian/layout.ts`
takes `kind` as a required parameter — a hand-authored props file with a moment
lacking `kind` is a type error, not a silent default: without it a claim+qualifier
hook fits as an ordinary moment and loses every hook-scoped token.

## Hand-editing the on-screen text and re-rendering

No agent is needed for a text fix. The on-screen text lives at exactly one JSON
path: `edit_decisions.persian.moments[].segments[].text` (plus `accentWords` on a
flat-hook hero). Edit those strings in the checkpointed `edit_decisions`, then
re-run the render:

```python
result = registry.get("persian_compose").execute({
    "edit_decisions": edit_decisions,
    "output_path": str(project_dir / "renders" / "final.mp4"),
})
```

Pass a `frames` slice (e.g. `"0-120"`) for a cheap preview of the edited moment
before committing to the whole render.

What editing alone does **not** do: the checkpoint copy and any props snapshot are
not render inputs, so changing them without re-running `persian_compose` changes
nothing on screen. And expect the same refusals a fresh edit meets — retired keys,
the reading-time ceiling, the per-role character caps (`MAX_*_CHARS` in
`lib/persian_moments.py`), the sync-drift tolerance in `lib/persian_sync.py`, the
silhouette band (`HOOK_SILHOUETTE_*` in `tokens.ts`), and the music record gate in
`lib/persian_music.py`. The check names its constants; the values live in code, not
here.

One trap no gate catches: a missing ZWNJ (U+200C) passes every audit and paints
wrong, because all comparisons and counts strip it. If an edited compound looks
joined or split on the frame, check the ZWNJ first.

## Checks before checkpoint

```python
from lib.persian_moments import audit_moments, build_moments
from lib.persian_sync import TimedWord, audit_sync, retime_moments
from lib.persian_text import normalize

moments = build_moments(authored_moments)
audit = audit_moments(moments, duration_seconds=duration_seconds)
assert not audit.problems, audit.problems
for advisory in audit.advisories:
    print("advisory:", advisory)      # judgement, not failure — read them

# Narrated mode: moments must be anchored to the voice, not rescaled from an old edit.
words = TimedWord.from_dicts(audio["wordTimings"])
sync = audit_sync(moments, words)
assert not sync.problems, sync.problems

# Shots must tile the timeline with no gap and no overlap.
for a, b in zip(shots, shots[1:]):
    assert abs(a["endSeconds"] - b["startSeconds"]) < 0.001, (a["id"], b["id"])

# Coverage: every second of the video is either footage or a typographic beat.
covered = sum(s["endSeconds"] - s["startSeconds"] for s in shots)
covered += sum(b["endSeconds"] - b["startSeconds"] for b in typographic_beats)
assert abs(covered - duration_seconds) < 0.5, f"{covered=} vs {duration_seconds=}"

# Footage-XOR-beat coverage is NOT evidence the screen is alive: a beat second
# counts as alive only while typography occupies it. `persian_compose` derives
# each plate window from the on-screen span of its typography, fails the run on
# a beat with none assigned, and refuses success when any contiguous run of
# >= 1.0s averages below YAVG 22 (runs below 30 pass with a warning — a
# legitimately dark shot measures ~28 and stays legal). Predict that gate here;
# do not be surprised by it.

# Orthography survived the copy into edit_decisions — every segment, not one field.
for moment in moments:
    for segment in moment.segments:
        assert normalize(segment.text) == segment.text
```

That last check is not paranoia. Text gets copied between four artifacts on its way
here, and a single copy through a tool that normalizes differently reintroduces
Arabic letters — which then render as a different word than the one that was
measured and approved.

Read the advisories rather than skipping them. They carry the judgements the audit
deliberately does not enforce: a set of nothing but statements, a density far off the
target, a gap so long the design has gone quiet. Each is legitimate on purpose
sometimes, which is exactly why a machine cannot decide it.

## Success criteria

- `audit_moments(...).problems` is empty.
- `audit_sync(moments, words).problems` is empty in narrated mode.
- 7–9 moments in a 60-second video; text coverage under 55%; first moment starts
  ≤ 0.6s.
- Every moment is one phrase: ordered `segments`, exactly one `hero` per reveal
  step, at most one `source` and it is last.
- No segment over its ceiling: hero 30, lead/tail 42, source 40 visible characters.
- No retired keys anywhere: `text`, `label`, `kicker`, `unit`, `highlight` on
  moments; `cues`, `hookText` in the block.
- Narrated mode: `music` + audited `musicTrack` (or an explicit `omitMusicReason`);
  `wordTimings` present for the `.srt` and the sync audit.
- Shots tile the timeline exactly; coverage matches the duration within 0.5s.
- Every shot has an attribution.
- Every segment's text passes `normalize(text) == text`.
- `render_runtime: "remotion"`, `composition_mode: "templated"`.
