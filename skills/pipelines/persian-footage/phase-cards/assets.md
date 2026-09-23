# Phase card — assets

- **Inputs:** audited `scene_plan` and narration audio when narrated.
- **Output:** schema-valid `asset_manifest`, timings, provenance, and inspected start/mid/end evidence.
- **Use:** deterministic asset manifest/checkpoint/music/region commands as they become available; never write `.workspace/*.py` for standard work.
- **Success:** one valid video per event, bounded search/download, subject intent preserved, and no duplicate download.
- **Stop:** quota exhaustion, invalid media probe, or tool gap. Record `tool_gap`; do not improvise a replacement script.
- **Details on demand:** `asset-director.md`.
