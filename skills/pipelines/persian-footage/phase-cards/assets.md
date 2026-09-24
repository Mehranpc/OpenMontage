# Phase card — assets

- **Inputs:** audited `scene_plan` and narration audio when narrated.
- **Output:** schema-valid `asset_manifest`, timings, provenance, and inspected start/mid/end evidence.
- **Use:** `python -m lib.persian_video_workflow assets build-manifest <project-id> [--overrides-json <path>]`, then `assets write-checkpoint <project-id> [--review-json <path>] [--metadata-json <path>]`; use `assets music search` / `assets music fetch` for cached music. In `review_subject_regions`, run `regions build-sheets <project-id>`, inspect the 10×10 start/middle/end sheets, then run `regions propose <project-id> --json <annotations.json>`. The proposal is non-final and requires explicit review before its `proposedEvidence` is used as final evidence. Never write `.workspace/*.py` for standard work.
- **Search budget:** provider search uses the pinned 180-second deadline and 6-hour project-local metadata cache; identical source/query/filter retries reuse cached results without another provider search.
- **Success:** one valid video per event, bounded search/download, subject intent preserved, no duplicate asset or music download, and an idempotent completed assets checkpoint.
- **Recovery:** never send `FILM_TYPE_LAYOUT` back to assets. For a named asset/region collision, reuse reviewed same-source window/crop first, then another reviewed existing candidate. Only exhausted shots may use `send-back <project-id> acquire_assets --code <code> --shot-id <shot-id> --reason <reason>`; the resulting scope must not widen to unrelated visual events or music.
- **Stop:** quota exhaustion, invalid media probe, or tool gap. Record it with `assets write-checkpoint <project-id> --tool-gap "<reason>"`; do not improvise a replacement script.
- **Details on demand:** `asset-director.md`.
