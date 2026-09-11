# Scene Director — Persian Footage Pipeline

## Your job

Turn the script into **semantic beats**, then express each footage beat as one or more
**visual events**. A semantic beat is a unit of meaning; a visual event is one shot-level
thing the viewer actually sees. They are deliberately not the same object.

Each non-typographic semantic beat owns `visual_events[]`. Every visual event independently
declares its approved `narration_span`, visual `intent`, concrete `subject` and `action`,
`desired_affect`, recurring `motif`, `visual_search_brief`, `shot_composition`,
`human_presence`, shot scale/environment/camera,
`shows_subject`, `importance`, `conflict_visibility`, `fallback_level`, and two English
search queries. Its durations must add back to the semantic beat.
The gate still reads old one-shot-per-beat checkpoints as one implicit visual event for
migration only; do not author new plans in that legacy shape.

## The translation problem

Pexels and Pixabay do not index Persian. A Persian query returns nothing or noise.
So every visual event needs English queries — but the translation that matters is of the
**visual intent**, not the words.

This is the single highest-leverage judgement in the pipeline. Two examples:

| Beat intent (fa) | Literal translation ✗ | Visual translation ✓ |
|---|---|---|
| «توجه، کمیاب است» | "attention is scarce" | `time lapse crowded subway commuters phones`, `close up eyes scrolling screen night` |
| «آرام شدن» | "becoming calm" | `slow motion water surface ripple morning`, `hands resting on table soft light` |

The literal queries return stock-photo abstractions — a lightbulb, a person holding
a sign. The visual queries return footage of something real that *means* the idea.

Rules that make queries work:

- **Concrete nouns only.** Cameras record objects, not concepts.
- **Add a qualifier.** `city` returns 10,000 unusable clips; `city street night rain
  overhead` returns a shot.
- **3–6 words.** Shorter is too broad, longer over-constrains and returns nothing.
- **2 queries per visual event.** Two different angles on the same visual, so one failing
  does not empty the beat. Not three: at 2 candidates per query a 12-beat video is
  already 24 downloads and several GB, and the third query is nearly always a
  paraphrase of the second rather than a genuine alternative.
- **Name the shot type when it matters**: `close up`, `aerial`, `slow motion`,
  `time lapse`, `overhead`.

### Semantic event contract and fallback ladder

A query is not the event. The event says what the viewer should understand and feel
before it says what to search. New events therefore carry:

- `narration_span`: exact approved-script words the event serves;
- `intent`, `subject`, `action`, `motif`: why the shot exists and what must be visible;
- `visual_search_brief`: a sentence describing the sought image before keywords;
- `shot_composition`: the intended spatial/action composition, not just shot scale;
- `desired_affect` and boolean `human_presence`;
- `importance`: integer 1–3. Higher importance consumes the bounded retry pass first;
  it does **not** raise `max_candidates_total` or the byte budget;
- `conflict_visibility`: a short explicit statement of whether/how the conflict is visible;
- `fallback_level`: `exact_literal` → `emotional_human` → `adjacent_metaphor` →
  `abstract`. `typography` is the terminal **beat-level** fallback, not a footage event.

For fear, conflict, embarrassment, distraction, stress, and relief, human presence is
preferred because a human reaction usually communicates the affect faster than an
object-only metaphor. The gate surfaces an object-only plan as an advisory rather than
pretending every emotional beat must contain a face.

The fallback ladder is ordered. Do not jump from a weak literal result to generic
abstract stock. Move down one level at a time, and let the asset manifest record why an
earlier level failed.

## The subject is not optional

This is the rule that was missing, and its absence produced a video about coffee
whose footage was a waist measurement, a bicep, a bathroom scale, test tubes, a
glucose monitor, a DNA render, and a blood-pressure cuff. Every one of those queries
was a defensible translation of its beat in isolation. Together they were a video
about a medical check-up.

**Name the video's subject before writing any query, and write it into the scene
plan as `subject`.** For «قهوه و هورمون» the subject is coffee: beans, a cup, a
pour, a grinder, a moka pot, someone drinking. Then:

### 1. Anchor quota

- The **first** footage visual event shows the subject literally.
- The **last** footage visual event shows the subject literally.
- At least **40%** of all footage visual events show the subject literally.

First and last are non-negotiable because they are the two frames a viewer decides
with: the first sets what the video is about, and the last is what they remember. A
video that opens on a laboratory and closes on a doctor is a video about medicine
whatever the narration says.

40% rather than a majority because the remaining beats have real work to do —
showing the mechanism, the study, the consequence. The quota is a floor on
recognisability, not a ceiling on variety.

### 2. Co-presence, not substitution

When a beat is about something else — a blood test, a hormone, a study — do not
replace the subject with that thing. Put **both in one frame**.

| Beat | Substitution ✗ | Co-presence ✓ |
|---|---|---|
| «قند خون» | `glucose meter check` | `coffee cup beside blood sugar monitor` |
| «چربی بدن کمتر» | `woman measuring her waist` | `athletic person drinking coffee gym morning` |
| «تحقیق روی ۲۲۶۴ نفر» | `laboratory researchers` | `hands holding coffee over open notebook desk` |

The co-presence frame carries the beat's meaning *and* keeps the subject on screen,
which is what makes twelve beats read as one video instead of twelve stock clips.

### 3. Banned vocabulary

Do not use these unless the script names them:

`doctor examining patient`, `blood test vials`, `DNA strand`, `laboratory
researchers`, `test tubes`, `scientist microscope`, `hospital`, `medical chart`,
`stethoscope`, `pills`, `capsules`, `measuring waist`, `measuring tape`,
`weighing scale`, `blood pressure cuff`, `syringe`, `nurse`, `clinic`.

`lib.persian_scenes.BANNED_QUERY_TERMS` is the authoritative list, matched as substrings
against the lowercased query — deliberately blunt, because a check that can be evaded by
word order is a check that will be.

These are the stock-library defaults for "health", and they are what a query returns
when it was written about the *topic* rather than about the shot. They are also
generic enough that the same twelve clips appear in every health video on the
internet, so a viewer has seen them and knows they mean nothing.

If a beat genuinely cannot be shot without one — the script says «آزمایش خون» —
use it, set `names_banned_term: true` on that beat, and pair it with the subject in the same
frame. The flag turns the gate's rejection into an advisory; it does not remove the
obligation to keep the subject in frame, which nothing can check for you.

Read that flag as a claim about the *script*, not about the beat's meaning. Coffee beat-10's
script says «دیابت», so `blood sugar monitor` is earned; `medication pills` is not, and a
plan written after this rule was rewritten still contained it.

## Orientation

Include an orientation hint matching the brief's format. Vertical footage is far
scarcer than landscape, so a vertical production needs queries chosen for what
actually exists vertically: a single subject close up, hands, a face, a pour. Wide
establishing shots are largely a landscape phenomenon, and asking for one vertically
returns a cropped landscape or nothing.

## Camera moves

Every visual event declares one. The vocabulary is fixed by `motion.ts`:

| Move | Use for | Why |
|------|---------|-----|
| `push-in` | Arriving at an idea, growing intensity | Reads as attention narrowing |
| `pull-out` | Revealing context, releasing tension | Reads as stepping back |
| `pan-left` / `pan-right` | Landscapes, crowds, lateral space | Follows the frame's own geometry |
| `none` | Footage that already has strong internal motion | Two motions fight |

Choose `none` deliberately and often. A clip that already contains movement —
running water, a moving crowd, a driving shot — does not need a camera move, and
adding one produces a queasy compound motion.

Do not alternate mechanically. Three consecutive `push-in` beats read as a tic.

## Visual variety

The rule is **no two adjacent visual events may share their shot scale and environment** —
not their subject.

This is the inverse of what it used to say, and the change is deliberate. The old
rule forbade repeating the subject, which is precisely the wrong constraint for a
video that needs its subject present in 40% of its visual events: obeying both is
impossible, and the subject is the one that matters. Variety comes from how the
subject is shot, not from replacing it.

So `close up pouring coffee kitchen` followed by `wide cafe window morning street`
is a cut, and so is `macro coffee beans texture` followed by `medium person drinking
coffee desk`. What reads as a mistake is two consecutive medium shots of a person
holding a cup indoors — same subject, same scale, same environment.

Vary at least one of:

- **Scale**: macro / close up / medium / wide / aerial
- **Environment**: kitchen / cafe / office / outdoors / studio / gym
- **Motion**: static / handheld / slow motion / time lapse

## Typographic beats

Only for beats the idea director marked infeasible, within the declared budget
(at most 2). Mark them explicitly with `typographic: true` and no `visual_events`. A
typographic beat renders as a near-black void plate of last resort (see the
asset-director for the full rule), never as a way to skip footage that exists.

If you find yourself wanting a third, the problem is upstream: send the brief back
rather than exceeding the budget. Three typographic beats in a 60-second video is
no longer a footage video.

## Scene plan metadata contract

`beats[]` carries narration meaning. `visual_events[]` carries shot-level execution.
Do not duplicate beat-level query/camera fields once `visual_events` exists.

```json
{
  "format": "vertical",
  "subject": "coffee",
  "beats": [
    {
      "id": "beat-1",
      "intent_fa": "شروع روز با قهوه",
      "script_line_fa": "هر روز صبح بدون قهوه روزت شروع نمی‌شه؟",
      "duration_seconds": 5,
      "typographic": false,
      "visual_events": [
        {
          "id": "beat-1-event-1",
          "duration_seconds": 2,
          "narration_span": "هر روز صبح بدون قهوه روزت شروع نمی‌شه؟",
          "intent": "make the morning coffee ritual instantly recognisable",
          "subject": "coffee",
          "action": "pouring coffee into a cup",
          "desired_affect": "curiosity",
          "motif": "morning ritual",
          "visual_search_brief": "real morning coffee ritual, tactile and unstaged",
          "shot_composition": "hands and cup dominate foreground; clean negative space above",
          "human_presence": true,
          "importance": 3,
          "conflict_visibility": "habit before the question lands",
          "fallback_level": "exact_literal",
          "camera": "push-in",
          "shows_subject": true,
          "shot_scale": "close up",
          "environment": "kitchen",
          "queries": [
            "close up pouring coffee morning",
            "steam rising coffee cup kitchen"
          ]
        },
        {
          "id": "beat-1-event-2",
          "duration_seconds": 3,
          "narration_span": "هر روز صبح بدون قهوه روزت شروع نمی‌شه؟",
          "intent": "move from hook to a relatable everyday routine",
          "subject": "coffee",
          "action": "holding coffee beside a notebook",
          "desired_affect": "recognition",
          "motif": "morning ritual",
          "visual_search_brief": "relatable coffee-at-desk routine with genuine hand action",
          "shot_composition": "overhead cup and notebook with hands entering frame",
          "human_presence": true,
          "importance": 2,
          "conflict_visibility": "none",
          "fallback_level": "exact_literal",
          "camera": "none",
          "shows_subject": true,
          "shot_scale": "overhead",
          "environment": "desk",
          "queries": [
            "coffee cup notebook desk",
            "hands holding coffee desk"
          ]
        }
      ]
    },
    {
      "id": "beat-7",
      "intent_fa": "معنا",
      "duration_seconds": 4,
      "typographic": true
    }
  ]
}
```

`desired_affect` states what the shot should make the viewer feel or anticipate; semantic
relevance alone is not enough. `shows_subject` is still literal evidence: a blurred shape
in the background does not count. `lib.persian_scenes.audit_scene_plan` validates event
identity, source-span/intent/action/motif/search-brief/composition completeness, human-presence policy, importance,
fallback level, event-duration coverage, subject quota, query count, and camera/variety
fields. Its `sourcing_order` sorts the bounded retry pass by importance without increasing
the shared candidate or byte ceilings.

## Before you checkpoint

Run the gate. Do not audit this list by reading it:

```python
from lib.persian_scenes import audit_scene_plan

audit = audit_scene_plan(scene_plan, typographic_budget=brief_budget)
assert not audit["problems"], audit["problems"]
for advisory in audit["advisories"]:
    print(advisory)          # read every one, answer it in the checkpoint metadata
```

It enforces the subject anchor quota, banned vocabulary, adjacent-variety rule, two
queries per visual event, declared camera move, event-duration coverage, semantic event
fields, desired affect, human-presence/fallback/importance contract, and typographic budget.

**Why a gate and not this checklist.** The checklist was here first, in exactly the form
below, and it was read. The plan written against it still contained `close up hands coffee
cup medication pills table` on the beat whose script says «دیابت» — the author had just read
the banned-vocabulary rule, and the beat felt like the exception the rule allows for. It was
not: the script names diabetes, not medication. A beat that feels like an exception is the
only situation where this rule is ever tested, and prose loses there every time.

When a beat genuinely earns a banned term, set `names_banned_term: true` on it. That
downgrades the rejection to an advisory rather than silencing it, because the flag cannot
tell whether the script really names the thing — only a human reading the line can.

The gate reports two kinds of finding. `problems` block the checkpoint. `advisories` are
the judgements deliberately left to you — a beat that leaves the subject entirely, or an
exempted banned term — and each one needs an answer in the checkpoint metadata, not a
dismissal.

What it checks, for reference:

- The plan names a `subject`.
- The first and last footage visual events have `shows_subject: true`.
- At least 40% of footage visual events have `shows_subject: true`.
- No query uses banned stock-medical vocabulary the script does not name.
- Every footage visual event has 2 English queries.
- Every footage visual event has a camera move, including a deliberate `none`.
- Every new visual event carries narration span, intent, subject, action, motif,
  visual_search_brief, shot_composition, human_presence, importance,
  conflict_visibility, and a legal fallback_level.
- Emotional affects without human presence and importance-3 events already at abstract
  fallback are surfaced as advisories for explicit review.
- No two adjacent visual events share both `shot_scale` and `environment`.
- Typographic beats are within budget.

And what it cannot check, so you must:

- Whether each query's words are concrete nouns rather than the abstract idea.
- Whether `shows_subject` is honest — a blurred shape in the background is not the subject,
  and nothing here can tell.
- Beat durations sum to within 10% of the target.
- Every beat's `script_line_fa` still passes `normalize(line) == line` — copying text
  between artifacts is where Arabic letters sneak back in.
