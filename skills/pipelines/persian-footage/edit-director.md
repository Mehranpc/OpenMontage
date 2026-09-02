# Edit Director — Persian Footage Pipeline

## Your job

Produce `edit_decisions` with a `persian` block: the exact props the composition
renders. This is where footage, script, and timings become one timeline.

## Build cues with the library, never by hand

```python
from lib.persian_cues import build_cues, audit_cues

cues = build_cues(word_timings)      # narrated mode
problems = audit_cues(cues)
assert not problems, problems
```

Hand-timed cues are the single most common source of unreadable Persian subtitles.
`build_cues` enforces reading speed (21 visible chars/second), the minimum on-screen
time, the character ceiling, and non-overlap — four limits that are easy to state and
easy to violate by eye. It also breaks at clause boundaries, so cues do not end
mid-thought.

In `silent` mode there are no word timings, so synthesize them from reading speed:
allocate each sentence `visible_length(text) / 15.0` seconds — 15 rather than the
21 ceiling, because with no voice setting the pace, subtitles at the ceiling feel
rushed. Then feed the synthesized words through `build_cues` exactly as in narrated
mode, so the same limits apply.

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

## Highlight phrases

At most **one per cue**, covering under half the cue's words.

Highlighting is emphasis, and emphasis that covers half a sentence emphasises
nothing. Choose the one word carrying the cue's meaning — usually a noun, rarely a
verb, never a function word.

Phrases are matched by normalized comparison, so «نیم‌فاصله» matches regardless of
which ک/ی encoding the source used. A multi-word phrase is treated as one unbreakable
unit by the line breaker, so it will never straddle a line break.

### One highlight must be placed for verification

The compose stage checks RTL reading order — the fault that no geometric measurement
can see — by locating the highlight's yellow and comparing its side of the frame
against the word's index. That check needs a cue built for it:

- **one line** (each line is centred independently, so a global word index maps to a
  horizontal position only on a single-line cue),
- **highlight on the first or last word** (a middle word sits near the line centre
  under either direction and proves nothing).

Your shortest cue is usually already one line. Give it a highlight on its first or last
word and note which cue it is in the checkpoint. Without one, compose has no way to
verify reading order and must report that it could not.

Karaoke emphasis will not do: it is scale and glow only, deliberately, because
colouring the spoken word would fight the highlight and changing its weight would
reflow the line.

## The `persian` block

```json
{
  "render_runtime": "remotion",
  "composition_mode": "templated",
  "renderer_family": "persian-footage",
  "persian": {
    "format": "vertical",
    "durationSeconds": 60.0,
    "hookText": "این متن *فارسی* است",
    "hookDurationSeconds": 3.5,
    "shots": [ … ],
    "cues": [ … ],
    "typographicBeats": [ { "id": "beat-7", "startSeconds": 30.0, "endSeconds": 34.0 } ],
    "audio": { "narration": "assets/narration.wav", "music": "assets/music/track.mp3" },
    "watermark": { "persianText": "طریقت تسلیم", "latinText": "@Pathway_of_Surrender" }
  }
}
```

`render_runtime` must be `"remotion"`. `persian_compose` refuses anything else, and
that refusal is deliberate: the composition depends on `FontFace` and canvas
measurement, neither of which exists on the other paths.

## The hook

Optional, 3–4 seconds, from the script's opening line. Mark one emphasis with
`*asterisks*`.

Keep it short — the hook renders at 63px vertical and wraps at 82% width, so more
than about eight words stops being a hook and becomes a paragraph.

## Timing checks before checkpoint

```python
from lib.persian_cues import audit_cues
from lib.persian_text import normalize

assert not audit_cues(cues)

# Shots must tile the timeline with no gap and no overlap.
for a, b in zip(shots, shots[1:]):
    assert abs(a["endSeconds"] - b["startSeconds"]) < 0.001, (a["id"], b["id"])

# Coverage: every second of the video is either footage or a typographic beat.
covered = sum(s["endSeconds"] - s["startSeconds"] for s in shots)
covered += sum(b["endSeconds"] - b["startSeconds"] for b in typographic_beats)
assert abs(covered - duration_seconds) < 0.5, f"{covered=} vs {duration_seconds=}"

# Orthography survived the copy into edit_decisions.
for cue in cues:
    assert normalize(cue.text) == cue.text
```

That last check is not paranoia. Text gets copied between four artifacts on its way
here, and a single copy through a tool that normalizes differently reintroduces
Arabic letters — which then silently break every highlight match.

## Success criteria

- `audit_cues` returns empty.
- Shots tile the timeline exactly; coverage matches the duration within 0.5s.
- Every shot has an attribution.
- At most one highlight phrase per cue, under half its words.
- **At least one single-line cue carries a highlight on its first or last word**, so
  compose can verify reading order.
- Every cue passes `normalize(text) == text`.
- `render_runtime: "remotion"`, `composition_mode: "templated"`.
