# Narration to Persian Video

Use this capability only for the middle production phases reported by `persian-video status`. The code state owns their order; this document only tells you which canonical contracts to execute.

For scene/moment planning, read `skills/pipelines/persian-footage/scene-director.md` and `edit-director.md`. Persist the normal `scene_plan`, `asset_manifest`, and `edit_decisions` checkpoints in manifest order; do not invent a second artifact system for the front door.

For acquisition, read `asset-director.md`. Every `direct_clip_search` call must first be passed through the code-owned budget clamp:

```bash
python -m lib.persian_video_workflow asset-request <project-id> --retry-pass 0 --json request.json
```

Execute exactly the returned request. Then account the tool's `result.data` before another pass:

```bash
python -m lib.persian_video_workflow asset-result <project-id> --retry-pass 0 --json result-data.json
```
The automatic path is exactly one primary pass plus at most one alternate-query retry. Provider set, candidate count, per-clip bytes, aggregate bytes, and clips per query come from `lib.persian_video_workflow`, not from agent judgment. Never raise a ceiling to make a difficult beat succeed.

Before accepting assets, review the actual subject region under the intended crop/camera path, preserving the subject-anchor requirements in the canonical scene/asset contracts. A relevance score or filename is not visual review.

Before rendering, read `skills/pipelines/persian-footage/final-candidate-protocol.md` and run its no-copy preflight. The preflight must use current-project paths and report zero media copies. Do not use `PersianCompose._build_props` directly and do not stage another project's media.

Render one final candidate through the canonical `compose-director.md` path. Retries require the state machine's attempt/send-back budget; do not create a gallery of final renders. The candidate is not approved merely because technical QA passes.

Use `guard-read` before any exploratory file read. A path denied by the guard is out of scope even if it appears useful for debugging or style reference.
