# Asset Director — Persian Footage Pipeline

Read the assets phase card first. Load `references/asset-acquisition.md` only for provider-budget, candidate-workspace, music, or alignment details needed by the current event.

## Output contract

Acquire one reviewed **video** candidate per footage visual event and produce canonical `asset_manifest`. Still images are forbidden. In narrated mode, timing is owned by the production front door; optionally acquire the licensed music bed required by policy.

## Bounded acquisition

Use `direct_clip_search` with `kind: "video"`, sources exactly `pexels` and `pixabay_video`, one primary query per event, `clips_per_query: 1`, matching orientation, duration floor, 1080 width floor and ceiling, 96 MiB per clip, 512 MiB aggregate, and 16 candidates total. Run at most one retry pass for unresolved events in audited importance order. Never widen providers, budgets, passes, or generic queries without a user decision.

```python
result = registry.get("direct_clip_search").execute({
    "queries": [{"query": "close up pouring coffee morning", "slot_id": "beat-1-event-1", "kind": "video"}],
    "sources": ["pexels", "pixabay_video"],
    "filters": {"orientation": "portrait", "min_duration": 6, "min_width": 1080, "max_width": 1080},
    "output_dir": str(project_dir / "assets"),
    "clips_per_query": 1,
    "max_candidates_total": 16,
    "max_bytes_per_clip": 100663296,
    "max_total_download_bytes": 536870912,
})
```

Follow the ordered fallback ladder: exact literal → emotional human → adjacent metaphor → abstract → beat-level typography. Record why each earlier level failed. Typography is last resort and must remain within budget.

## Durable candidate lifecycle

Use `python -m lib.persian_video_workflow asset-request`, persist the bounded provider result with `asset-result`, then stage/review/reject/select candidates through the official candidate commands. Identity is provider/source + exact source window + intended crop. Review the actual crop/window at start, middle, and end; persist subject/human continuity, affect, semantics, crop safety, staged-stock risk, and resolution.

Selection must copy returned `manifestBinding` and `manifestEvidence` into the canonical row. Do not recreate the pool in chat, rename files to invent identity, or use `.workspace/*.py` as a ledger.

## Subject-region review

After the completed assets checkpoint advances the run to `review_subject_regions`, use `python -m lib.persian_video_workflow regions build-sheets <project-id>`. Inspect the generated start/middle/end frames and grouped 10×10 sheets, write only the grid annotations, then run `regions propose <project-id> --json <annotations.json>`. Each shot annotation must include `shot_id`, non-empty `observed`, and exactly one `start`, `middle`, and `end` frame. A frame is either `{"position":"start","priority":"hard","grid":{"x1":1,"y1":2,"x2":7,"y2":8}}`, `{"position":"middle","regions":[...]}` for multiple hard/soft boxes, or `{"position":"end","clear":true}` when review finds no protected region. Grid coordinates are integer cell boundaries from 0 through 10.

The resulting `proposal.json` is derived, has `confirmationRequired: true`, and deliberately keeps candidate evidence under `proposedEvidence`; do not treat the proposal itself as confirmed review evidence. After explicit review, validate/use only the reviewed evidence through the existing subject-region validator. Do not recreate `build_region_sheets.py`, `grid_sheets.py`, or `build_subject_regions.py` under `.workspace/`.

Music-only manifest changes do not invalidate the visual subject-region sheet fingerprint. The index may refresh provenance, but cached PNG frames/sheets must be reused when visual asset windows and scene geometry are unchanged.

## Shot-local recovery

A `FILM_TYPE_LAYOUT` fit failure stays in `no_copy_preflight`; repair the named layout/typography/reveal timing within its bounded recovery policy and do not reacquire footage. For `ASSET_SELECTION_HARD_REGION_COLLISION`, inspect already reviewed options for each named shot in this order: a reviewed non-overlapping window/crop from the selected source, then another reviewed existing candidate. Only a shot with no valid reviewed option may return to acquisition.

Use the machine-scoped front door only for those exhausted shots: `python -m lib.persian_video_workflow send-back <project-id> acquire_assets --reason "<reason>" --code ASSET_SELECTION_HARD_REGION_COLLISION --shot-id <shot-id> [--shot-id <shot-id> ...] [--edit-attempt-id <attempt-id>]`. Every such rewind consumes the normal send-back budget. The resulting reacquisition scope permits search/stage/review/reject/select only for its named visual events and forbids unrelated music mutation; never reacquire the whole asset set for one defective shot.

## Selection rules

A candidate must honestly serve narration intent and `desired_affect`, retain required subject/human presence through the whole selected crop, fit duration/orientation/resolution, leave feasible type geometry, and have low/medium staged-stock risk. High risk is rejected. Distinct non-overlapping windows from one source are allowed; visible overlap is not.

Every row records semantic/visual-event IDs, narration span, authored query/rank, provider/source identity, exact source window/crop, dimensions/duration, licence/attribution, fallback evidence, selection/relevance reasons, affect, subject/human evidence, and start/middle/end review.

## Timing front door

Before alignment run:

```bash
python -m lib.persian_video_workflow alignment-plan <project-id>
```

Then use durable `alignment-start` → `alignment-status` → `alignment-commit`. `execute_alignment_with_fallback` is a low-level worker/test primitive, not the production entrypoint. Never invoke registry transcriber providers directly from asset sourcing; provider selection and fallback belong to the production front door. The approved script owns words; provider timings are only a clock.

## Music

Use `pixabay_music`, instrumental, long enough for the video. Persist a complete `musicTrack` with path, provider, licence name/URL/date, attribution, and honest Content-ID risk. Narrated mode requires the record unless deliberate silence is stated. The edit artifact owns runtime music; do not duplicate it under audio.

## Gate

```python
from lib.persian_assets import assert_video_only, audit_asset_manifest

assert_video_only(manifest)
problems = audit_asset_manifest(manifest, scene_plan)
assert not problems, problems
```

Also ffprobe every selected file. Require exactly one valid asset per footage event, no duplicate clip identity, current workspace selection/evidence, full attributions, and survival of the scene-plan subject quota. Stop on exhausted budget, invalid media, provider/tool gap, missing evidence, or no honest candidate; do not substitute an image or improvise a script.