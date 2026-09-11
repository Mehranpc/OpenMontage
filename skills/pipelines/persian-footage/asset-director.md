# Asset Director — Persian Footage Pipeline

## Your job

Acquire, per visual event, one **video** clip that means what its parent semantic beat says and matches that event's `desired_affect`. In `narrated`
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
with little free disk that difference matters, and it wastes minutes per visual event.

```python
result = registry.get("direct_clip_search").execute({
    # First pass: ONE primary query and ONE candidate per footage visual event.
    # Use the visual event's second query only for an unresolved event in a bounded retry.
    "queries": [
        {"query": "close up pouring coffee into cup morning", "slot_id": "beat-1-event-1", "kind": "video"},
    ],
    "sources": ["pexels", "pixabay_video"],
    "filters": {
        "orientation": "portrait",
        "min_duration": 6,
        # Keep portrait footage at the production width instead of fetching 1440px variants.
        "min_width": 1080,
        "max_width": 1080,
    },
    "output_dir": str(project_dir / "assets"),
    "clips_per_query": 1,
    "max_candidates_total": 16,
    "max_bytes_per_clip": 100663296,       # 96 MiB
    "max_total_download_bytes": 536870912, # 512 MiB
})
```

The parameter is `clips_per_query`. `per_query` is not a key this tool accepts.
For this pipeline it is always `1`: one primary candidate per footage visual event on the
first pass, then the unused second query only for unresolved events. The hard
`max_candidates_total`, per-clip byte ceiling, and aggregate byte ceiling are required
on every call; raising them requires an explicit user decision, not an agent retry.

`orientation` is `"portrait"` for vertical, `"landscape"` for landscape. Add
`min_duration` at or above the longest beat, so clips too short to fill a beat never
get downloaded in the first place.

### Resolution: declare both the floor and ceiling

`_pick_video_rendition` in `tools/video/stock_sources/pexels.py` otherwise takes the
**largest** rendition at or below 1920px *wide*. For a portrait clip "width" is the
short edge, so `min_width: 1080` alone is only a floor: a vertical clip can still arrive
at 1440×2560 or 1440×2732 and waste bytes before a 1080×1920 render downsamples it.

Set both `min_width: 1080` and `max_width: 1080`. The source adapters choose a rendition
inside that interval before download, and `direct_clip_search` enforces the same maximum
against declared metadata and the ffprobe result. A source with no suitable 1080-wide
rendition is unresolved; do not widen the ceiling just to make the search succeed.

On the 12-beat run this avoids spending the shared byte budget on 1440-wide detail the
render discards. Keep both width bounds on every Persian vertical stock request.

**Pexels honours `orientation`; Pixabay does not.** `direct_clip_search` therefore
runs `ffprobe` after every download and deletes a mismatch before it can enter the
candidate set. Unknown pre-download geometry is not permission to keep the bytes.

Use only `sources: ["pexels", "pixabay_video"]` in this production pipeline. NASA,
Archive.org, Wikimedia, NARA, LOC, Pond5 and exploratory provider cascades are outside
the approved path. Never create `smoke-*` directories under a production project. If a
provider needs investigation, stop and do it in an isolated diagnostic directory after
explicit approval.

Run one batched first pass containing one primary query per footage visual event and
`clips_per_query: 1`. Inspect those results. Run at most one second pass for unresolved
events, using their already-authored alternate query and the remaining shared byte and
candidate budget. Consume that retry pass in `audit_scene_plan(...)["sourcing_order"]`:
importance-3 events first, then 2, then 1. Importance changes **priority**, never the
shared `max_candidates_total`, per-clip limit, aggregate byte ceiling, provider list, or
number of passes. Do not widen providers, add generic queries, or start a third pass.

### Ordered fallback hierarchy

Search/selection follows the event's declared level in order:

`exact_literal` → `emotional_human` → `adjacent_metaphor` → `abstract` → typography.

The first four are footage levels. Typography is a semantic-beat fallback and remains
subject to the typographic budget. A selected asset below `exact_literal` records a
`fallback_reason` naming why earlier levels failed; otherwise the gate refuses it. This
is what prevents a difficult event from silently widening into generic stock.

## Selection

Inspect the candidates. Do not select on filename or on the API's relevance score —
both are unreliable, and a clip selected without being seen is how a video ends up
with footage that contradicts its narration.

Inspect the **actual selected crop/window** at start, middle, and end. A single API
thumbnail cannot reveal a late actor entrance, reframing, or a subject leaving the crop.
Persist `frame_review: {start, middle, end, observed}` as evidence; all three booleans
must be true and `observed` must say what remained in frame. A quick extraction can use:

```bash
ffmpeg -y -ss <sample-second> -i clip.mp4 -frames:v 1 -vf scale=320:-1 thumb.jpg
```

Then judge, in priority order:

1. **Does it mean the semantic beat?** A clip that is beautiful and wrong is wrong.
2. **Does it produce the visual event's `desired_affect`?** Record the match in the selection reason; a semantically correct shot with the wrong emotional read is still the wrong event.
3. **Does it hold the subject the scene plan declared?** For a visual event with
   `shows_subject: true`, the subject has to be legible — a blurred shape in the
   background does not count. This is the check that catches a clip which matched its
   query and still moved the video off its topic.
4. **Is it long enough?** Source duration ≥ beat duration. A clip that has to loop
   inside one beat reads as a glitch.
5. **Does the orientation match?** Portrait for vertical, landscape for landscape.
   A landscape clip cropped to vertical loses its subject to the crop.
6. **Can footage and type be solved together?** Read the provisional display
   requirement; inspect the cropped window at start/middle/end and record genuine
   negative space plus conservative subject envelopes. Do not assume a fixed text band.
   Keep ranked alternatives until no-copy edit preflight chooses a feasible pair.
7. **Is the motion compatible?** Fast internal motion plus a camera move is queasy.
   If the clip moves a lot, revisit the beat's camera and set `none`.
8. **Does it look staged/generic?** Record `staged_stock_risk` as low/medium/high.
   High is rejected. Emotional events should preserve the planned human presence rather
   than accepting a generic object shot because it technically matches the noun.

Reject freely. Rejecting a clip costs one more search; shipping a wrong clip costs
the video's credibility.

### Record why, not just what

Write `selection_reason` naming what is visibly in frame and a separate
`relevance_reason` explaining why that image serves the semantic beat. Also record the
actual authored `query`, `candidate_rank`, `affect_match`, `human_presence`,
`staged_stock_risk`, `semantic_beat_id`, `visual_event_id`, exact `narration_span`,
`source_in_seconds`, duration, fallback level/reason, and start/middle/end `frame_review`.
«قهوه در فنجان روی میز کار» is a selection reason; "best match" is not.

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

Timings are a **clock**, never delivery copy. The approved script owns the words; these
word timings align that copy for sidecar SRT, burned captions, hybrid delivery, and
narration-anchored moments. In burned/hybrid mode drift is visibly on screen, so timing
coverage is a real delivery concern again; the remedy is matching narration/timings,
never substituting Whisper spelling for approved Persian.

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
      "semantic_beat_id": "beat-1",
      "visual_event_id": "beat-1-event-1",
      "narration_span": "هر روز صبح بدون قهوه روزت شروع نمی‌شه؟",
      "query": "close up pouring coffee morning",
      "candidate_rank": 1,
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
      "human_presence": true,
      "affect_match": true,
      "staged_stock_risk": "low",
      "fallback_level": "exact_literal",
      "selection_reason": "فنجان قهوه و دست در قاب، بخار در نور صبح",
      "relevance_reason": "عمل واقعی ریختن قهوه همان عادت صبحگاهی beat را نشان می‌دهد",
      "frame_review": {
        "start": true, "middle": true, "end": true,
        "observed": "فنجان، دست و عمل ریختن در کل پنجرهٔ انتخابی باقی می‌مانند"
      }
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

- Every footage visual event has exactly one asset. Legacy checkpoints without `visual_events` are treated as one implicit event per beat.
- New visual-event assets carry the full semantic/selection evidence listed above;
  `audit_asset_manifest` rejects missing identity, un-authored queries, affect mismatch,
  high staged-stock risk, lost required human/subject presence, undocumented fallback,
  or incomplete start/middle/end inspection.
- No clip_id fills two visual events. Reuse is visible and reads as running out of material.
- `ffprobe` agrees with the recorded duration and dimensions on every clip — the
  APIs' metadata is occasionally wrong, and a clip shorter than its beat renders
  black at the tail.
- **The anchor quota survived selection.** The first and last footage visual events have
  `shows_subject: true`, and at least 40% of footage visual events do. The scene plan asked for
  this; selection is where it gets lost, because the beat whose subject clip was
  unusable is exactly the beat where a generic one is tempting.
- Every selected portrait clip is requested with `min_width: 1080` and `max_width: 1080`.
  A 1440-wide clip means the width ceiling was omitted and the run spent more of the shared
  byte budget than the 1080×1920 render needs.
- In `narrated` mode: word timings cover the narration duration end to end.
