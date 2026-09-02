# Compose Director — Persian Footage Pipeline

## Your job

Render the video, then **look at it**. A schema-valid `render_report` proves nothing
about whether the Persian is readable.

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
`cues`, not a cut list; `video_compose`'s adapters have no representation for word
timings or Persian line-break constraints.

Defaults worth knowing:

- **`crf: 16`** — the glass panel's blurred gradient and the film grain are the first
  things a higher CRF destroys, and banding inside a frosted panel is very visible.
- **`timeout_ms: 60000`** — per frame. The default 30s can expire while a cold font
  cache loads Estedad.
- **`scale`** — below 1.0 for a quick check. Text is still measured at full size, so a
  half-scale render validates layout honestly. Ship at 1.0.

### Iterating cheaply

Disk on this machine is nearly full and renders are minutes long. Verify a section
before committing to the whole thing:

```python
inputs["frames"] = "0-120"     # first four seconds
```

Render the hook, one mid-video cue, and the watermark's migration separately. Three
short renders find more problems than one long one, for less time and less disk.

## Verification — this is the actual work

A render that completes tells you the props were well-formed. It says nothing about
the two things this pipeline exists to get right.

Use `lib/persian_verify.py`. Do not write your own pixel checks: the obvious ones do
not work, and the section at the end of this file records which ones were tried and
what defeated each. Everything below is measured, not asserted.

### Extract frames

Sample the middle of each cue — not the boundaries, where enter and exit animations are
mid-flight.

```python
import json, subprocess
import numpy as np
from PIL import Image

frames = []
for cue in edit_decisions["persian"]["cues"]:
    n = int((cue["startSeconds"] + cue["endSeconds"]) / 2 * 30)
    path = f"renders/frames/{cue['id']}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "renders/final.mp4",
                    "-vf", f"select=eq(n\\,{n})", "-vsync", "0", "-frames:v", "1", path],
                   check=True)
    frames.append((cue["id"], np.asarray(Image.open(path).convert("RGB")).astype(int)))
```

### Measure them

```python
from lib.persian_verify import verify_frames

summary = verify_frames(frames, fmt=edit_decisions["persian"]["format"])
if not summary["passed"]:
    for problem in summary["problems"]:
        print(problem)
```

`verify_frames` returns `passed`, `problems`, `frames_with_text`, and a per-frame
measurement. Each problem names its own likely cause. What it checks, and what each
failure means:

| Measured | Failure means |
|---|---|
| Ink inside the subtitle band | Font did not load (tofu has no ink where glyphs belong), or the panel did not render |
| Line count against the format's cap | The fitter and the renderer disagree about the line budget |
| Horizontal extent inside the panel envelope | Layout measured against a different font than the one that painted |
| Centre within 2% of frame centre | The panel's flex centring is not taking effect |
| Contrast ≥ 2.99:1 | **The panel did not render.** Not a grading problem — see below |

The contrast floor is a derived guarantee, not a preference. The panel is
`rgba(20,20,20,0.45)`, so footage of brightness `f` composites to `0.55f + 9`, capped at
149 for pure white footage. White text on 149 is 2.99:1. A reading below that is
arithmetically impossible while the panel is painting, so it means the text is sitting
directly on the clip. Real renders measure 5.98–18.9:1.

`frames_with_text` empty across every frame is reported separately — that is either
wrong sampling or a failed font, and both are worth distinguishing from a layout fault.

### Reading order

The measurement above cannot see reversed text: «است فارسی متن این» occupies the same
pixels as the correct order. `check_reading_order` locates the yellow `#FFEA00` of a
**highlight phrase** and compares its side of the frame against the word's index.

It has three preconditions, each checked and reported rather than assumed:

- **The cue needs a `highlightPhrases` entry.** Karaoke emphasis is scale and glow only,
  by design, so an unhighlighted cue has no coloured word and nothing to locate.
- **The cue must be a single line.** Each line is centred independently, so on two lines
  the first word of line 2 sits at the right of line 2 while its global index is halfway
  through the cue.
- **The highlighted word must not be near the middle**, where it sits near the line
  centre under either direction.

```python
from lib.persian_verify import check_reading_order

# A cue you deliberately built for this: one line, highlight on its first word.
order = check_reading_order(frame, highlight_word_index=0, word_count=5, fmt="vertical")
assert order["rtl_order_correct"], order
```

In RTL the first word is on the **right**. An early-index highlight landing left of
centre means a container lost `direction: rtl`.

Plan for this at the edit stage: give at least one short single-line cue a highlight
phrase on its first or last word. Verified on the 60-second proof render, «راه‌حل،» as
word 1 of 5 measured at x 371-433 of 540 (right), and «است.» as word 5 of 5 at 129-175
(left).

The band restriction matters. Footage contains yellow — a sunset frame in that same
render carried 37 `#FFEA00` pixels outside the subtitle band, which without the
restriction read as a highlight left of centre, i.e. a reported failure on a correct
render.

### Watermark

The watermark cannot be found by looking at one frame. It is white type at 0.6 opacity
with no panel behind it, so it composites to roughly `0.6·255 + 0.4·footage` — a value
bright footage produces on its own. Pass a reference render with the mark removed:

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
`tokens.ts` by a contract test, so it cannot drift away from where the renderer draws:

| Format | Quiet | Resting | Phases (of `durationInFrames`) |
|---|---|---|---|
| vertical | 46% | 15% | quiet to 20%, bloom +60f, decay +60f, migration +45f |
| landscape | 62% | 8% | same |

The quiet position differs because it is derived from the subtitle band, which differs.
`clipped_at_edge` catches the `translateX`/position pair drifting apart, which only
shows on long text.

Without a reference, `find_watermark` works on a **footage-free** render (`shots: []`)
and refuses to guess on anything else. That is a cheap standalone check of all four
phases and the migration path, and it needs no second render of the real video.

On the 60-second proof render the mark measured rows 446-457 while quiet and 144-159 at
rest, never clipped.

Two things to know about the numbers it returns. On an MP4 pair the vertical extent is
exact but the horizontal extent widens by tens of pixels, because H.264 scatters
differences into neighbouring columns — enough for presence and clipping, not for
measuring width. And the mark's own soft shadow forms a faint halo contiguous with the
glyph rows, which is why the detector applies a floor relative to the strongest row;
without it the reported extent grows from 14 rows to 89.

### Check the file

```bash
ffprobe -v error -show_entries stream=codec_type,width,height,channels \
        -show_entries format=duration -of default=noprint_wrappers=1 final.mp4
```

- Dimensions exactly 1080×1920 or 1920×1080.
- Duration within 1 second of planned.
- Audio stream present when narration or music was specified. A silent video that was
  supposed to have narration is a broken promise, not a minor defect.

### Audio: verify the duck, not just the presence of a stream

`music_mixed: true` in the render report means the music was *ducked under the
narration*, which an `ffprobe` stream listing cannot tell you. Measure it:

```python
import subprocess
import numpy as np

pcm = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", "renders/final.mp4",
     "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
    capture_output=True, check=True,
).stdout
samples = np.frombuffer(pcm, dtype=np.float32)

def rms(start_s, span_s=0.3):
    window = samples[int(start_s * 48000) : int((start_s + span_s) * 48000)]
    return float(np.sqrt((window ** 2).mean()))

# Inside a cue the music is at musicDuckVolume; between cues it returns to base.
inside = rms(cues[0]["startSeconds"] + 0.5)
between = rms(cues[0]["endSeconds"] + 0.15)
```

With narration, `between` should exceed `inside` — that ratio *is* the duck. The levels
are `0.6` base and `0.36` ducked, so expect roughly 1.6× in the music component; with
narration present in both windows the raw RMS difference is smaller, so compare the
music band rather than the whole signal if the margin is unclear.

With no narration, music sits flat at `0.5` and both windows read the same. A ducking
pattern in a music-only render means `audio.narration` leaked in from somewhere.

Measured on a two-cue proof render: music at 3.66 inside cues against 10.04 between them
with narration present, and a constant 7.02 with narration absent.

### What must never ship

Tofu boxes and reversed reading order. Both are immediately obvious to a Persian reader
and both make the video look broken rather than imperfect. The measurements above catch
each one specifically.

### Do not reinvent the pixel checks

Each of these was implemented, measured against real renders, and abandoned. They are
listed because every one of them looks correct until it is tested.

| Approach | What defeated it |
|---|---|
| `mask = a.max(axis=2) > 200` for text | Selects bright footage. Sun on water scores higher than the glyphs |
| Row-mean dip to find the panel | The dip is ≈1 unit over real footage; missed the panel on 7 of 8 frames |
| Brightness threshold for the watermark | 35% of one search band came back as "watermark" |
| Local contrast for the watermark | Textured footage is bright pixels next to dark ones. False positive of 5003px against the mark's 792 |
| Row-gradient energy | Footage detail beat the mark 26:1 against 21:1 |
| Temporal invariance across frames | H.264 re-quantizes the static mark every frame, so it is not invariant in the output |

The working versions are all in `lib/persian_verify.py`, with the reasoning at each
threshold. `tests/lib/test_persian_verify.py` builds synthetic frames whose correct
answer is known by construction, and `tests/contracts/test_persian_geometry_parity.py`
pins the geometry constants against `tokens.ts` so the verifier cannot drift into
measuring a band the subtitle is not in.

## If the render fails

`persian_compose` diagnoses the three common failures in its error message. Beyond
those:

| Symptom | Cause | Fix |
|---|---|---|
| Hangs, no frames | `delayRender` never resolved — font missing | Confirm `public/fonts/estedad/` exists and `--public-dir` was not overridden |
| "does not fit" throw | A cue exceeds the layout floor | Shorten the cue at the edit stage; do not lower the floor |
| Black beats | Clip not staged under `public/` | Check `public_path` in the manifest |
| Frame timeout | Large clip's first frame decode | Raise `timeout_ms` |

Do **not** resolve a render failure by switching runtime. If Remotion is genuinely
broken, raise a structured blocker. A HyperFrames swap produces fallback-font layout,
which looks plausible and is wrong — and it discards the measurement guarantees that
every check in this file depends on.

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
  "persian_text_verified": true,
  "verification_frames": ["renders/frames/cue-01.png"],
  "verification_notes": "8/8 cues measured: 1-2 lines, inside panel envelope, centred within 1px, contrast 5.98-18.9:1. RTL order confirmed on cue-4. Watermark resting rows 148-161, not clipped.",
  "attributions": ["Video by Jane Doe on Pexels", "…"],
  "music_mixed": true
}
```

`persian_text_verified` is set by **you**, and only when `verify_frames(...)["passed"]`
is `True` and `check_reading_order` confirmed the highlight side on at least one cue.
`persian_compose` returns it as `false` and cannot know otherwise — it renders, it does
not look. Setting it true without those measurements defeats the only check that catches
the failures this pipeline was built to prevent.

`verification_notes` should carry the numbers, not adjectives: contrast range, line
counts, and the watermark's measured rows. "Looks good" is not a verification record.

`attributions` must cover every clip — both stock licences require it.
