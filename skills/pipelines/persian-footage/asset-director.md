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