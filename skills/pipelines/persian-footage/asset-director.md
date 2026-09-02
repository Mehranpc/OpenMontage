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
  query changes. Never substitute a photo.

## Acquisition

Pass `filters.orientation` matching the brief's format. This is the single most
important input to this stage's efficiency: without it, Pexels returns mostly
landscape, and a vertical production downloads ten clips to keep two. On a machine
with little free disk that difference matters, and it wastes minutes per beat.

```python
result = registry.get("direct_clip_search").execute({
    "queries": [
        {"query": "city street night traffic overhead", "slot_id": "beat-1", "kind": "video"},
        {"query": "neon signs rain night close up",     "slot_id": "beat-1", "kind": "video"},
    ],
    "filters": {"orientation": "portrait", "min_duration": 6},
    "output_dir": str(project_dir / "assets" / "clips"),
    "per_query": 3,
})
```

`orientation` is `"portrait"` for vertical, `"landscape"` for landscape. Add
`min_duration` at or above the longest beat, so clips too short to fill a beat never
get downloaded in the first place.

**Pexels honours `orientation`; Pixabay does not.** Its API has no orientation
parameter, so `pixabay_video` results arrive unfiltered and are usually landscape.
Probe every downloaded clip with `ffprobe` and discard the mismatches yourself rather
than trusting the filter to have applied:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 clip.mp4
```

Fan out all beats' queries in one call rather than per beat — the tool parallelizes
internally, and per-beat calls serialize the network waits.

Download 2–3 candidates per query. The extra cost is small and having a second
option when the first is wrong saves a re-run of the whole stage.

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
2. **Is it long enough?** Source duration ≥ beat duration. A clip that has to loop
   inside one beat reads as a glitch.
3. **Does the orientation match?** Portrait for vertical, landscape for landscape.
   A landscape clip cropped to vertical loses its subject to the crop.
4. **Is there room for text?** The subtitle panel occupies the lower third. A clip
   whose subject sits exactly there will be covered by it.
5. **Is the motion compatible?** Fast internal motion plus a camera move is queasy.
   If the clip moves a lot, revisit the beat's camera and set `none`.

Reject freely. Rejecting a clip costs one more search; shipping a wrong clip costs
the video's credibility.

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
if the machine can carry it. A smaller model's Persian word boundaries drift, and
karaoke emphasis on drifted timings is worse than no karaoke: it lands on the wrong
word, which the viewer reads as a bug.

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
compete with narration and with subtitles simultaneously.

Get a track at least as long as the video; the composition loops it, and a short
loop becomes obvious.

## Manifest contract

```json
{
  "format": "vertical",
  "assets": [
    {
      "beat_id": "beat-1",
      "kind": "video",
      "path": "assets/clips/pexels_1234567.mp4",
      "public_path": "clips/pexels_1234567.mp4",
      "duration_seconds": 12.4,
      "width": 1080,
      "height": 1920,
      "source_in_seconds": 2.0,
      "provider": "pexels",
      "original_url": "https://www.pexels.com/video/1234567/",
      "license": "Pexels License",
      "attribution": "Video by Jane Doe on Pexels"
    }
  ],
  "word_timings": [
    { "word": "شهر", "start": 0.0, "end": 0.42, "probability": 0.98 }
  ],
  "music": { "path": "assets/music/track.mp3", "attribution": "…", "duration_seconds": 95.0 }
}
```

`public_path` matters: the composition resolves clip paths through Remotion's
`staticFile()`, so every clip must end up under `remotion-composer/public/`. Copy or
symlink it there and record the path relative to `public/`. A clip left outside
`public/` renders as a black beat with no error.

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
- In `narrated` mode: word timings cover the narration duration end to end.
