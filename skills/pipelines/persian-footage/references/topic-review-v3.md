# Topic-level footage review (pipeline profile `v3_staged`, #387 increment 1)

Status: **experimental, opt-in**. The default profile is still `v2`; nothing
changes for existing projects. v3 becomes default only after the full #387
staged architecture (increments 2–6) passes real acceptance.

## Enabling

1. Set `metadata.pipeline_profile: "v3_staged"` in the scene plan.
2. Export `OPENMONTAGE_PIPELINE_PROFILE=v3_staged` in the environment.
   Without the env opt-in a v3 plan is refused (`PipelineProfileError`).

## Stage-1 admission question

Stage 1 asks only: *is this footage about the topic of this narration
event, appropriate, and technically usable?* It does **not** evaluate text
placement, negative space, carrier bands, crop geometry, hook role, affect,
staged-stock risk, human presence or subject focus. Text and watermark
adapt to locked footage in later stages (#387 Stages 3–4).

Mechanical rules (provenance, licence, duration, frame review
start/middle/end + observed, dark-footage check, cost ceilings) still apply.

## `topic_review` (required in the candidate review)

```json
{
  "topic_match": "on_topic | off_topic",
  "inappropriate": false,
  "placeholder_screen": false,
  "technical_usable": true,
  "observed": "what the reviewer actually saw"
}
```

Unknown fields are refused. Rejection codes:

| Code | Meaning |
|---|---|
| `TOPIC_REVIEW_MISSING` | no valid `topic_review` |
| `TOPIC_OFF` | footage is not about the event topic |
| `CONTENT_INAPPROPRIATE` | inappropriate content |
| `PLACEHOLDER_SCREEN` | green/chroma or blank placeholder screen (owner decision: always unusable) |
| `TECHNICAL_UNUSABLE` | otherwise technically unusable |

Under v3 the candidate-review response reports
`carrierPremeasure: {"status": "not_applicable", "profile": "v3_staged"}`.

## Stage locks and forward-only flow (#387 increment 2)

Under `v3_staged`, completing `plan_scenes_moments` writes
`stage_locks/stage-0.json` (narration & timing: script + scene-plan
checkpoints) and completing `acquire_assets` writes `stage_locks/stage-1.json`
(footage: assets checkpoint). Each lock records file SHA-256s, the digests
of the earlier locks it consumed, and the implementation SHA.

After a lock:

- rewriting its checkpoints is refused (`write_checkpoint`);
- the `.asset-workspace` is read-only after the footage lock;
- `reconcile-plan` (stage 0) and `reopen-asset-search` (stage 1) are refused;
- every phase completion re-verifies all locks; any mutation stops the run.

There is no automatic backward transition: every agent `send-back` is
refused, and a user-directed send-back into a locked stage is refused too.
Text and watermark adapt to locked footage (increments 3–4); the only
future backward path is the human time-range revision (increment 5).

## Stage 3: styled text adapts to locked footage (#387 increment 3)

A v3 edit sets `persian.pipelineProfile: "v3_staged"`; it must equal the plan's
profile (checked at `no_copy_preflight` completion). Under v3 the geometric
hard-region precheck and the review-region negative-space refusal do not run,
and the browser prepass never refuses for subject geometry. Each moment is
placed by a fixed ladder, recorded in `filmType.stagedText[<moment>].step`:

1. `free_area` – the profile's own placement outside reviewed subject regions;
2. `band` – explicit top/bottom band zone at the first fitting size;
3. `scaled_band` – the same band at a smaller ladder size (never below the floor);
4. `scrim` – band zone with the profile's strong field, subject regions ignored
   (regions are evidence only; safe area, copy and timing stay hard);
5. `subtitle_fallback` – no legible placement: the moment paints nothing
   (`subtitleFallback: true`) and the stage-2 subtitle stays; a warning records it.

Copy and timing contracts (well-formed segments, reading time) still refuse:
they are stage-0 truth. Stage 3 never changes footage and never sends work back.

## Stage 4: the brand never blocks (#387 increment 4)

Under v3 the watermark keeps today's dynamic planner (including the #230
spacing rules) but can never refuse the render. Only two constraints apply:
inside the watermark safe zone, and the text distance. Faces and subjects are
not obstacles. If the planner refuses or leaves the brand below its coverage
floor, each uncovered interval after the intro delay (in timeline order, until
the floor is met) uses the in-safe-zone anchor farthest from the text painting
then, staying put while the current anchor still keeps the text distance.
Every added slot has reason `v3-farthest-from-text` and is listed in
`filmType.stagedWatermark.filledSlots` with its measured text gap; a coverage
shortfall is a warning, never a `WATERMARK_COVERAGE` refusal.
