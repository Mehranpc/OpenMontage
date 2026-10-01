# Asset Director — Persian Footage Pipeline

Read the assets phase card first. Load `references/asset-acquisition.md` only for provider-budget, candidate-workspace/admission, music, or alignment details needed by the current event.

## Output contract

Acquire one reviewed **video** candidate per footage visual event and produce canonical `asset_manifest`. Still images are forbidden. In narrated mode, timing is owned by the production front door; optionally acquire the licensed music bed required by policy.

## Bounded acquisition

Use `direct_clip_search` with `kind: "video"`, sources exactly `pexels` and `pixabay_video`, one primary query per event, `clips_per_query: 1`, matching orientation, duration floor, 1080 width floor and ceiling, 96 MiB per clip, 512 MiB aggregate, and a candidate ceiling of two per planned footage event: at least 16, at most 32, enforced by `asset-request` (#246). Run at most one retry pass for unresolved events in audited importance order, and only after review: stage and review (or reject) every candidate the first pass found first. The retry must carry a query for every event whose candidates were all rejected; `asset-request` refuses it otherwise (#239). A duplicate source is a technical rejection, so reject it; do not spend the retry on it before review. Never widen providers, budgets, passes, or generic queries without a user decision.

**Recovery inside the pass budget is not a user decision (#331).** When review rejects candidates (band not clear, subject absent, dark window), do not ask the user how to proceed while a retry pass remains. Read `status` → `acquisition`: it lists `remainingPasses`, `unresolvedEvents` and the one `nextStep`. Do exactly that: reject each failing candidate with its measured reason, `reconcile-plan` a band the footage does not keep clear where another clear region exists, then run the next retry pass for the events still without a candidate. Ask the user only to widen providers, budgets or passes, and a send-back is only for when `remainingPasses` is empty and events are still unresolved. Never state that the search budget is exhausted unless `remainingPasses` is empty.

When the retry is spent and events still lack usable footage, the plan's queries are the problem, not its timing. `reconcile-plan` accepts `{"visual_event_id":"ve-7","queries_append":["phone resting on table, plain wall above"]}`: it records at most two new queries per event as `reconciled_queries`, and keeps the authored `queries` so existing selections stay valid. Then run `python -m lib.persian_video_workflow reopen-asset-search <project-id> --visual-event-id ve-7 [...] --reason "..."`. It spends one send-back, scopes a fresh pass cycle to exactly those events and stays in acquire_assets. A manifest row may cite an appended query. That needs no replan and no user decision; ask only when the send-back budget is spent.

Supply queries and filters in the project-local request; the durable front door owns the destination and remaining download ceilings:

```json
{
  "queries": [{"query": "close up pouring coffee morning", "slot_id": "beat-1-event-1", "kind": "video"}],
  "filters": {"orientation": "portrait", "min_duration": 6, "min_width": 1080, "max_width": 1080}
}
```

`asset-search` owns admission; do not admit manually first. Exceptional direct-provider `output_dir` must be an absolute current-project path; relative paths resolve beneath the project root.

Provider-search metadata is cached under the project for 6 hours using source + query + filters as the key. An identical retry reuses the cached candidate list without another provider API search or cache rewrite; filter changes or expiry re-query the provider. Cached search metadata never becomes selection truth: media still passes validation and candidate review/selection remains in the durable asset workspace.

Run the pass through the front door rather than calling the tool inline, so provider wait is measured and the pass has a resume identity:

```bash
python -m lib.persian_video_workflow asset-search <project-id> --retry-pass 0 --request <project>/search-request-0.json
```

Write the request to a project-local path and leave it unchanged once the pass starts: the pass's identity is *(retry pass, exact request bytes)*, so a crash mid-download reconciles the same logical search — `python -m lib.persian_run_kernel status <project-id> <job-id>` — instead of paying for it twice. `--no-wait` starts it and returns for sessions that cannot block.

Follow the ordered fallback ladder: exact literal → emotional human → adjacent metaphor → abstract → beat-level typography. Record why each earlier level failed. Typography is last resort and must remain within budget.

## Durable candidate lifecycle

Run the bounded pass with `asset-search` (which owns `asset-request` → `direct_clip_search` → `asset-result` as one durable execution), then stage/review/reject/select candidates through the official candidate commands. The durable pass is measured work, not phase advancement: the phase still completes through `complete --phase acquire_assets`. Identity is provider/source + exact source window + intended crop. Review the actual crop/window at start, middle, and end; persist subject/human continuity, affect, semantics, crop safety, staged-stock risk, and resolution.

Select each valid reviewed candidate when accepted; review-before-retry does not require deferring valid selections until every search pass finishes. Retry only unresolved events, while preserving the requirement to review or reject every primary-pass candidate first.

Selection must copy returned `manifestBinding` and `manifestEvidence` into the canonical row. Do not recreate the pool in chat, rename files to invent identity, or use `.workspace/*.py` as a ledger.

## Band evidence at candidate review (#261)

For every `carries_moment` event, `asset-candidate-review` requires `frame_review.subject_grid`: the selected window's `start`, `middle` and `end` frames in the same 10×10 annotation format `regions propose` takes (`{"priority":"hard","grid":{...}}`, `{"regions":[...]}`, or `{"clear":true}`). A hard region that overlaps the event's declared `negative_space` (and every `negative_space_alternates` entry) is refused as `[BAND_OCCUPIED:<band>]`; when the footage leaves an alternate clear, record that region as `frame_review.placement_space`, by the same rule region review enforces. The message lists the regions that stay clear *and* can host type in the plan's format (#335): in Film Type vertical that is only `centre_band`, because columns are narrower than the narrowest curated column and the lower band is the caption reserve. `none` means the footage has no usable way out; reject it. Reject that candidate (`asset-candidate-reject --category technical`), or `reconcile-plan` the band, before you select. Reuse the same grid when you annotate `regions propose` for that shot.

Candidate review also pre-measures the planned `moment_copy` against these regions using the existing render-free Film Type browser prepass (#341), before selecting pass-0 footage or spending pass 1. `[CARRIER_COPY_UNPLACEABLE]` is a measured hard-region refusal: reject or repair the plan first. The command returns `carrierPremeasure`; `unknown` (missing copy/font/browser or another layout error) is not a fit approval. This screen does not replace region review, edit preflight, or rendered acceptance, and does not acquire assets or change retry budgets.

## Subject-region review

After the completed assets checkpoint advances the run to `review_subject_regions`, use `python -m lib.persian_video_workflow regions build-sheets <project-id>`. Inspect the generated start/middle/end frames and grouped 10×10 sheets, write only the grid annotations, then run `regions propose <project-id> --json <annotations.json>`. Each shot annotation must include `shot_id`, non-empty `observed`, and exactly one `start`, `middle`, and `end` frame. **In every shot whose asset has `human_presence: true`, each non-clear frame must mark the face as `"face":{"x1":..,"y1":..,"x2":..,"y2":..}` (merged as a hard region), or `"face_visible": false` when the face is off frame or turned away (#230).** Typography avoids hard regions only; a face left unmarked, or marked only as soft body occupancy, is exactly where the hook lands. **Every shot that starts inside the first 5 seconds (under the opening hook) must also state `"visual_complexity": "simple"` or `"busy"`** from the reviewed frames: `simple` for a broad low-detail field, `busy` for dense texture, signage, screens or crowds. Film Type 2.16 chooses the hook contrast treatment from it; carry the same value into that shot's `visualComplexity` in `edit_decisions` (#269). Mark the head generously, from hairline to chin. A frame is either `{"position":"start","priority":"hard","grid":{"x1":1,"y1":2,"x2":7,"y2":8}}`, `{"position":"middle","regions":[...]}` for multiple hard/soft boxes, or `{"position":"end","clear":true}` when review finds no protected region. Grid coordinates are integer cell boundaries from 0 through 10.

**Correcting the plan against reviewed footage is `reconcile-plan`, not a send-back.** When frame review shows the plan's declarations are wrong about footage you already have (the subject is absent, so `shows_subject` is false; a carrier's clear region is another one; the moment belongs on a different event), run `python -m lib.persian_video_workflow reconcile-plan <project-id> --json <amendments.json> --reason "..."` with `{"amendments":[{"visual_event_id":"ve-4","set":{"shows_subject":false}}]}`. Only `shows_subject`, `negative_space`, `carries_moment`, `fallback_level` and `moment_copy` can be reconciled; timing, queries and ids still need a real replan. It spends no send-back and keeps acquisition state. If the corrected plan no longer matches the manifest, it archives only the assets checkpoint and returns to `acquire_assets` so you rebuild the manifest from the durable workspace, with no new download (#224). Use send-back only when the plan needs new footage or new timing.

`regions propose` also reports `openingHookPlacement`: which Film Type hook zones stay clear of reviewed hard regions over the first 5 seconds. When none does, `review_subject_regions` refuses (`OPENING_HOOK_UNPLACEABLE`, #229): open on a shot whose subject leaves a hook zone clear, or re-source the opening, instead of discovering it with edit candidates.

`regions propose` also reports `negativeSpaceCollisions`: every `carries_moment` event whose declared `negative_space` a reviewed hard region occupies, with the regions that stay clear. `review_subject_regions` refuses to complete while the current proposal lists any (`DECLARED_NEGATIVE_SPACE_OCCUPIED`, #214). Resolve them before edit with `reconcile-plan` (move the moment carrier or re-declare the region against the footage), or correct the annotation if the review drew it wrong. The edit stage refuses the same collision after spending candidates.

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

Default: `pixabay_music`, instrumental, long enough for the video, selected without asking the user. Use a user-named or user-supplied track only when the request provided one (and still record its licence). Persist a complete `musicTrack` with path, provider, licence name/URL/date, attribution, and honest Content-ID risk. Narrated mode requires the record unless deliberate silence is stated. The edit artifact owns runtime music; do not duplicate it under audio.

## Gate

```python
from lib.persian_assets import assert_video_only, audit_asset_manifest

assert_video_only(manifest)
problems = audit_asset_manifest(manifest, scene_plan)
assert not problems, problems
```

Also ffprobe every selected file. Require exactly one valid asset per footage event, no duplicate clip identity, current workspace selection/evidence, full attributions, and survival of the scene-plan subject quota. Stop on exhausted budget, invalid media, provider/tool gap, missing evidence, or no honest candidate; do not substitute an image or improvise a script.