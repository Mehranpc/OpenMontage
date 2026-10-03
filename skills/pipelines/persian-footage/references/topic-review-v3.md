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
