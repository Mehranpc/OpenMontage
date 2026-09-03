# Scene Director — Persian Footage Pipeline

## Your job

Turn the script into a beat list where every beat carries **English search queries**
that will actually return usable video, plus a camera move.

## The translation problem

Pexels and Pixabay do not index Persian. A Persian query returns nothing or noise.
So every beat needs English queries — but the translation that matters is of the
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
- **2 queries per beat.** Two different angles on the same visual, so one failing
  does not empty the beat. Not three: at 2 candidates per query a 12-beat video is
  already 24 downloads and several GB, and the third query is nearly always a
  paraphrase of the second rather than a genuine alternative.
- **Name the shot type when it matters**: `close up`, `aerial`, `slow motion`,
  `time lapse`, `overhead`.

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

- The **first** beat shows the subject literally.
- The **last** beat shows the subject literally.
- At least **40%** of all footage beats show the subject literally.

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

Every beat declares one. The vocabulary is fixed by `motion.ts`:

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

The rule is **no two adjacent beats may share their shot scale and environment** —
not their subject.

This is the inverse of what it used to say, and the change is deliberate. The old
rule forbade repeating the subject, which is precisely the wrong constraint for a
video that needs its subject present in 40% of its beats: obeying both is
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
(at most 2). Mark them explicitly with `typographic: true` and no queries.

If you find yourself wanting a third, the problem is upstream: send the brief back
rather than exceeding the budget. Three typographic beats in a 60-second video is
no longer a footage video.

## Scene plan metadata contract

```json
{
  "format": "vertical",
  "subject": "coffee",
  "subject_queries": ["coffee cup", "coffee beans", "pouring coffee", "moka pot"],
  "beats": [
    {
      "id": "beat-1",
      "intent_fa": "شروع روز با قهوه",
      "script_line_fa": "هر روز صبح بدون قهوه روزت شروع نمی‌شه؟",
      "duration_seconds": 5,
      "camera": "push-in",
      "typographic": false,
      "shows_subject": true,
      "shot_scale": "close up",
      "environment": "kitchen",
      "queries": [
        "close up pouring coffee into cup morning",
        "steam rising from coffee cup kitchen"
      ]
    },
    {
      "id": "beat-10",
      "intent_fa": "ارتباط با دیابت",
      "duration_seconds": 6,
      "camera": "pull-out",
      "typographic": false,
      "shows_subject": true,
      "shot_scale": "close up",
      "environment": "kitchen table",
      "names_banned_term": true,
      "queries": [
        "coffee cup beside blood sugar monitor table",
        "close up coffee cup on kitchen table morning light"
      ]
    },
    {
      "id": "beat-7",
      "intent_fa": "معنا",
      "duration_seconds": 4,
      "camera": "none",
      "typographic": true,
      "shows_subject": false,
      "queries": []
    }
  ]
}
```

`shows_subject` is what makes the anchor quota checkable rather than aspirational.
Set it honestly: a clip where the subject is a blurred shape in the background does
not show the subject.

## Before you checkpoint

Run the gate. Do not audit this list by reading it:

```python
from lib.persian_scenes import audit_scene_plan

audit = audit_scene_plan(scene_plan, typographic_budget=brief_budget)
assert not audit["problems"], audit["problems"]
for advisory in audit["advisories"]:
    print(advisory)          # read every one, answer it in the checkpoint metadata
```

It enforces the subject anchor quota, the banned vocabulary, the adjacent-variety rule,
two queries per beat, a declared camera move, and the typographic budget.

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
- The first and last footage beats have `shows_subject: true`.
- At least 40% of footage beats have `shows_subject: true`.
- No query uses banned stock-medical vocabulary the script does not name.
- Every non-typographic beat has 2 English queries.
- Every beat has a camera move, including a deliberate `none`.
- No two adjacent beats share both `shot_scale` and `environment`.
- Typographic beats are within budget.

And what it cannot check, so you must:

- Whether each query's words are concrete nouns rather than the abstract idea.
- Whether `shows_subject` is honest — a blurred shape in the background is not the subject,
  and nothing here can tell.
- Beat durations sum to within 10% of the target.
- Every beat's `script_line_fa` still passes `normalize(line) == line` — copying text
  between artifacts is where Arabic letters sneak back in.
