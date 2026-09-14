# Persian Final Review

Use this capability only when code reports `final_review` or `awaiting_human`.

Read `skills/pipelines/persian-footage/compose-director.md`, `final-candidate-protocol.md`, and `hook-quality.md`. Run the canonical media, Persian text, layout/crop, audio, subtitle, provenance, retention, and hook-quality checks against the one current-project candidate. Record measured evidence in the normal `render_report`/review artifacts; do not replace those contracts with prose in workflow state.

The final non-human review must record `retention_audit`, `post_render_motion_qa`, `silent_watch_audit`, `cut_rhythm`, `caption_readability`, `strongest_scene`, `weakest_scene`, `hook_strength`, and `resolution_strength`. Watch the candidate muted for the silent-watch fields; do not infer comprehension from subtitle presence or timeline metadata. `retention_audit.problems` must be empty and `post_render_motion_qa.passed` must be true before semantic review can advance. The motion audit samples the finished MP4 pixels; its long near-static runs are evidence that authored event changes did not become visible changes. Silent-watch main point/hook direction/conclusion must all be understood, and hook/resolution strength must be at least `acceptable` before the candidate can advance. For `burned_captions`/`hybrid`, inspect real caption frames: one/two lines, safe-area clearance, no overlap with moments, and no watermark collision; persist at least entry/mid/exit paths as `render_report.caption_verification_frames`. For `sidecar_only`/`hybrid`, verify the SRT exists and matches the approved-script alignment.

For any current production carrying a `hookQualityAudit`, the review of the actual MP4 must also persist `final_review.metadata.hookQualityReview`. It must contain `version: "1.0"`, a `strength` of `weak` / `acceptable` / `strong`, a non-empty rationale, at least two opening-specific observations from the rendered candidate, `mutedHookDirectionConfirmed`, `visualVoiceAlignment`, and `payoffBeginsPromptly`. This is a real-render backstop: timeline metadata cannot certify that the opening actually communicates the predicted tension. A weak rendered hook, failed muted direction, weak visual/voice alignment, or delayed payoff blocks presentation even when structural retention passed. Historical reviews without `hookQualityAudit` remain readable and do not need synthetic backfilled evidence.

Persist the normal `final_review` artifact inside the current project with `status: pass`, `recommended_action: present_to_user`, at least four real reviewed frame paths, passing technical/audio/promise/subtitle checks, and `output_path` pointing to the same digest-bound MP4. Set `render_report.final_review_ref` to that exact artifact. Workflow state stores only the validated artifact path/hash and candidate path/hash; it never substitutes prose evidence for the artifact.

The compose checkpoint must be written as `awaiting_human`, never self-approved. Its primary output must be an MP4 inside this project's directory with a 64-character SHA-256 matching the exact file bytes, `delivery_status="final_candidate"`, `human_visual_approval=false`, and `persian_text_verified=false`.

After final QA is persisted, advance the front-door state only through the code API:

```bash
python -m lib.persian_video_workflow attempt <project-id> --phase final_review
python -m lib.persian_video_workflow complete <project-id> --phase final_review --evidence-json final-review-evidence.json
# final-review-evidence.json contains only: {"final_review_path":"artifacts/final_review.json"}
python -m lib.persian_video_workflow complete <project-id> --phase awaiting_human
```
The final command independently re-reads `checkpoint_compose.json`, resolves the reported render path, refuses a render outside this project, re-hashes the MP4 bytes, and only then changes workflow status to `awaiting_human` with `next_phase=null`.

At that point **stop**. Present that exact candidate to the user and wait for explicit approval. Approval and compose completion continue through the existing digest-bound checkpoint protocol; this front-door skill never treats silence, a general goal, or an earlier approval as approval of the candidate.
