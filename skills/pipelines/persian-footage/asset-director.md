# Asset Director — Persian Footage Pipeline

## Your job

Acquire, per beat, one **video** clip that means what the beat says. In `narrated`
mode, also produce word-level timings from the narration audio. Optionally acquire
music.

## The hard rule: video only

**Still images are forbidden.** This is a gate, not advice — `lib.persian_assets.assert_video_only`
rejects any manifest containing an image entry, and the compose stage will not run
on a rejected manifest.

Why it is absolute: a still under Persian text reads as a slideshow, and the motion
grammar has nothing to work with. A camera move over a still is the Ken Burns
effect, which belongs to a different genre.

Concretely:

- `direct_clip_search` with `kind: "video"` on every query. Never `"any"` — `"any"`
  lets an image through when video results are thin, which is exactly when you are
  most tempted to accept it.
- Do not call `pexels_image`, `pixabay_image`, or any `image_generation` tool.
- If no video exists for a beat, the beat becomes typographic (within budget) or the
  query changes. Never substitute a photo. A typographic beat renders as an opaque
  void plate in `voidBackground` (`#0B0B0C`, measured luma ~17/255) — a viewer reads
  that near-black screen as a broken or missing clip, not as art direction.
- The plate is a LAST RESORT: never mark a beat typographic while any unused,
  thematically usable downloaded candidate exists on disk for that scene. Check the
  downloaded candidates first, and record in the checkpoint which candidates you
  checked and why none of them can serve the beat.
- Every typographic beat must carry typography across its whole window.
  `persian_compose` derives the plate from the on-screen span of its typography and
  fails the run on a beat with none assigned, so an empty plate second is a failed
  run, not a covered one.

## Acquisition

Pass `filters.orientation` matching the brief's format. This is the single most
important input to this stage's efficiency: without it, Pexels returns mostly
landscape, and a vertical production downloads ten clips to keep two. On a machine
with little free disk that difference matters, and it wastes minutes per beat.

```python
result = registry.get("direct_clip_search").execute({
    "queries": [
        {"query": "close up pouring coffee into cup morning", "slot_id": "beat-1", "kind": "video"},
        {"query": "steam rising from coffee cup kitchen",     "slot_id": "beat-1", "kind": "video"},
    ],
    "filters": {
        "orientation": "portrait",
        "min_duration": 6,
        # Resolution floor *and* ceiling in one number — see below.
        "min_width": 1080,
    },
    "output_dir": str(project_dir / "assets" / "clips"),
    "clips_per_query": 2,
})
```

The parameter is `clips_per_query`. `per_query` is not a key this tool accepts, and
because the schema ignores unknown keys it silently falls back to the default of 3 —
which is how a 12-beat run became 36 downloads instead of 24.

`orientation` is `"portrait"` for vertical, `"landscape"` for landscape. Add
`min_duration` at or above the longest beat, so clips too short to fill a beat never
get downloaded in the first place.

### Resolution: `min_width` is also the ceiling

`_pick_video_rendition` in `tools/video/stock_sources/pexels.py` takes the **largest**
rendition at or below 1920px *wide*. For a portrait clip "width" is the short edge, so
the cap does nothing: a vertical clip arrives at 1440×2560 or 1440×2732, which is 22–52
MB per clip for a 1080×1920 render that then downscales it.

Setting `min_width: 1080` fixes both ends at once, because the picker sorts descending
and takes the first candidate within `[min_width, 1920]`:

- clips whose best rendition is below 1080 wide are rejected outright, and
- among the rest the 1080 rendition is still the largest that fits, so nothing above it
  is fetched.

On the 12-beat run this is the difference between roughly 300 MB and roughly 80 MB.

Do not try to fix this inside `direct_clip_search` or the Pexels adapter. Both are
shared with `documentary-montage`, which renders landscape and wants the 1920-wide
rendition; changing the default there would silently degrade a pipeline this one has
nothing to do with.

**Pexels honours `orientation`; Pixabay does not.** Its API has no orientation
parameter, so `pixabay_video` results arrive unfiltered and are usually landscape.
Probe every downloaded clip with `ffprobe` and discard the mismatches yourself rather
than trusting the filter to have applied:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 clip.mp4
```

Fan out all beats' queries in one call rather than per beat — the tool parallelizes
internally, and per-beat calls serialize the network waits.

Download 2 candidates per query, so 2 queries per beat gives 4 candidates to choose
from. That is enough to have an alternative when the first is wrong and few enough that
a 12-beat vertical run stays inside a few hundred megabytes.

## Selection

Inspect the candidates. Do not select on filename or on the API's relevance score —
both are unreliable, and a clip selected without being seen is how a video ends up
with footage that contradicts its narration.

Extract a thumbnail per candidate:

```bash
ffmpeg -y -ss 1 -i clip.mp4 -frames:v 1 -vf scale=320:-1 thumb.jpg
```

Then judge, in priority order:

1. **Does it mean the beat?** A clip that is beautiful and wrong is wrong.
2. **Does it hold the subject the scene plan declared?** For a beat with
   `shows_subject: true`, the subject has to be legible — a blurred shape in the
   background does not count. This is the check that catches a clip which matched its
   query and still moved the video off its topic.
3. **Is it long enough?** Source duration ≥ beat duration. A clip that has to loop
   inside one beat reads as a glitch.
4. **Does the orientation match?** Portrait for vertical, landscape for landscape.
   A landscape clip cropped to vertical loses its subject to the crop.
5. **Can footage and type be solved together?** Read the provisional display
   requirement; inspect the cropped window at start/middle/end and record genuine
   negative space plus conservative subject envelopes. Do not assume a fixed text band.
   Keep ranked alternatives until no-copy edit preflight chooses a feasible pair.
6. **Is the motion compatible?** Fast internal motion plus a camera move is queasy.
   If the clip moves a lot, revisit the beat's camera and set `none`.

Reject freely. Rejecting a clip costs one more search; shipping a wrong clip costs
the video's credibility.

### Record why, not just what

Write a one-line `selection_reason` per asset into the manifest, naming what is in
frame. «قهوه در فنجان روی میز کار» is a reason; "best match" is not.

This is the artifact a reviewer reads to see whether the footage is about the video's
subject, and it is what made the coffee run's failure visible only after rendering: the
manifest recorded twelve chosen clips and nothing about what any of them showed, so
"waist measurement" and "coffee cup" looked identical at the checkpoint.

## Word timings (`narrated` mode)

```python
result = registry.get("mlx_whisper_transcriber").execute({
    "input_path": str(narration_path),
    "language": "fa",          # never omit — Persian is misdetected as Arabic or Urdu
    "output_dir": str(project_dir / "assets"),
})
```

`language: "fa"` is not optional. Auto-detection on short or music-heavy audio
misfires, and a transcript in the Arabic script looks plausible while being wrong in
every letter that matters.

Falls back to `transcriber` when MLX is unavailable — with `model_size: "large-v3"`
if the machine can carry it. A smaller model's Persian word boundaries drift.

Timings feed the sidecar `.srt` rather than any on-screen text, so drift of a tenth of
a second is now cosmetic instead of a visible bug. Accuracy is still worth having —
subtitles that lag the voice are irritating — but it is no longer a reason to block the
stage.

### Reconciling transcript against script

The transcript is what was *said*; the script is what was *written*. They differ —
the narrator rephrases, repeats, or skips.

The **script wins for text**; the **transcript wins for timing**. Use the transcript's
word timings, but keep the script's orthography: transcribers do not reliably emit
ZWNJ, so transcript text alone would fail the orthography gate.

Where they diverge beyond a word or two, say so at the checkpoint. A narrator who
improvised a whole sentence has changed the video, and that is the user's decision.

## Music

`pixabay_music` is the only available provider. Instrumental, no vocals — vocals
compete with the narration.

Get a track at least as long as the video; the composition loops it, and a short
loop becomes obvious. The bed is **not optional** when narration is present: the
gate refuses a narrated project with no music record (`lib/persian_music.py`).
Record provenance fully so a downstream licence or Content-ID question can be
answered without re-discovery.

The record is a **`musicTrack`** object (``lib.persian_music.MusicTrack`` /
``build_music_track``) and it is the **single statement** of the music choice:

```json
{
  "path": "projects/<project>/assets/music/bed.mp3",
  "source": "pixabay_music",
  "license": { "name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/", "downloadedAt": "2026-09-03" },
  "attribution": "Calm Ambient — leberch",
  "contentIdRisk": { "level": "low", "reason": "Pixabay Content Licence permits commercial use; third-party claims remain theoretically possible and are recorded, not excluded" }
}
```

Rules:

- **One record, one place:** state the bed as ``edit_decisions.persian.musicTrack``.
  ``persian_compose`` stages ``musicTrack.path`` and builds ``audio.music`` itself;
  stating both ``musicTrack`` and ``persian.audio.music`` is a hard refusal — the
  tool cannot tell which file the licence covers (this exact refusal tripped on the
  real project when both were set). See the compose-director music-refusal paragraphs
  for the single-statement rule and the licence-honesty wording.
- **Required for narrated mode:** ``audit_music`` refuses ``narrated=True`` with
  no track unless deliberate silence is recorded as ``omitMusicReason``.
  ``unknown`` risk needs explicit ``acknowledgeUnknownMusicRisk``; ``high`` risk is
  refused outright. Pixabay Content Licence is Instagram-safe; ``contentIdRisk``
  must use honest "low, recorded" wording — never "guaranteed zero". ``musicFadeSeconds``
  defaults to 1.5s; volumes are flat 0.5 / base 0.6 / duck 0.36.
- **Manifest vs edit decisions:** the asset manifest records the *selected* audio
  clip that was staged; the **edit decisions** carry the word timings and the
  music record. Word timings travel as ``persian.audio.wordTimings`` (the 149-word
  list in the real project, from the transcriber output), not as a top-level
  ``word_timings`` key. The manifest's music entry should show the full
  ``musicTrack`` shape above when the project is narrated; a bare
  ``{path, attribution}`` is stale.

## Manifest contract

```json
{
  "format": "vertical",
  "assets": [
    {
      "beat_id": "beat-1",
      "kind": "video",
      "path": "projects/<project>/assets/video/selected/beat-1_pexels_1234567.mp4",
      "duration_seconds": 12.4,
      "width": 1080,
      "height": 1920,
      "source_in_seconds": 2.0,
      "provider": "pexels",
      "original_url": "https://www.pexels.com/video/1234567/",
      "license": "Pexels License",
      "attribution": "Video by Jane Doe on Pexels",
      "shows_subject": true,
      "selection_reason": "فنجان قهوه روی میز، بخار در نور صبح"
    }
  ],
  "musicTrack": {
    "path": "projects/<project>/assets/music/bed.mp3",
    "source": "pixabay_music",
    "license": { "name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/", "downloadedAt": "2026-09-03" },
    "attribution": "Calm Ambient — leberch",
    "contentIdRisk": { "level": "low", "reason": "Pixabay Content Licence permits commercial use; third-party claims remain theoretically possible and are recorded, not excluded" }
  }
}
```

Record `path` as the real location on disk — that is the field `persian_compose` reads.
It copies each shot's source into `public/persian/<run-id>/` at render time and deletes
the directory afterwards, so **do not pre-stage clips under `public/` and do not treat
`public_path` as required.** It was required once, and nothing consumed it: the coffee run
recorded `clips/pexels_*.mp4` for all twelve assets, nothing was ever written to
`public/clips/`, and the video rendered correctly. What actually produces a black beat is a
`path` that does not resolve, and `audit_asset_manifest` now checks exactly that.

## Verification before checkpoint

```python
from lib.persian_assets import assert_video_only, audit_asset_manifest

assert_video_only(manifest)                 # raises on any image entry
problems = audit_asset_manifest(manifest, scene_plan)
assert not problems, problems
```

Also confirm by hand:

- Every non-typographic beat has exactly one asset.
- No clip_id fills two beats. Reuse is visible and reads as running out of material.
- `ffprobe` agrees with the recorded duration and dimensions on every clip — the
  APIs' metadata is occasionally wrong, and a clip shorter than its beat renders
  black at the tail.
- **The anchor quota survived selection.** The first and last footage beats have
  `shows_subject: true`, and at least 40% of footage beats do. The scene plan asked for
  this; selection is where it gets lost, because the beat whose subject clip was
  unusable is exactly the beat where a generic one is tempting.
- Every clip is at most 1920px on its long edge. A 2732px clip means `min_width` was
  omitted, and the run just downloaded several times more data than it needed.
- In `narrated` mode: word timings cover the narration duration end to end.
