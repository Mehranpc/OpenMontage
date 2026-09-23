# Phase card — assets

- **Inputs:** audited `scene_plan` and narration audio when narrated.
- **Output:** schema-valid `asset_manifest`, timings, provenance, and inspected start/mid/end evidence.
- **Use:** `python -m lib.persian_video_workflow assets build-manifest <project-id> [--overrides-json <path>]`, then `assets write-checkpoint <project-id> [--review-json <path>] [--metadata-json <path>]`; never write `.workspace/*.py` for standard work.
- **Success:** one valid video per event, bounded search/download, subject intent preserved, no duplicate download, and an idempotent completed assets checkpoint.
- **Stop:** quota exhaustion, invalid media probe, or tool gap. Record it with `assets write-checkpoint <project-id> --tool-gap "<reason>"`; do not improvise a replacement script.
- **Details on demand:** `asset-director.md`.
