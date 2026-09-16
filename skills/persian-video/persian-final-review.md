# Persian Final Review

Use this capability only when code reports `final_review` or `awaiting_human`.

Read `skills/pipelines/persian-footage/compose-director.md`, `final-candidate-protocol.md`, and `hook-quality.md`. Run the canonical media, Persian text, layout/crop, audio, subtitle, provenance, retention, and hook-quality checks against the one current-project candidate. Record measured evidence in the normal `render_report`/review artifacts; do not replace those contracts with prose in workflow state.

The final non-human review must record `retention_audit`, `post_render_motion_qa`, `silent_watch_audit`, `cut_rhythm`, `caption_readability`, `strongest_scene`, `weakest_scene`, `hook_strength`, and `resolution_strength`. Watch the candidate muted for the silent-watch fields; do not infer comprehension from subtitle presence or timeline metadata. `retention_audit.problems` must be empty and `post_render_motion_qa.passed` must be true before semantic review can advance. The motion audit samples the finished MP4 pixels; its long near-static runs are evidence that authored event changes did not become visible changes. Silent-watch main point/hook direction/conclusion must all be understood, and hook/resolution strength must be at least `acceptable` before the candidate can advance.

For `burned_captions`/`hybrid`, inspect real caption frames: one/two lines, safe-area clearance, no overlap with moments, and no watermark collision; persist at least entry/mid/exit paths as `render_report.caption_verification_frames`. For `sidecar_only`/`hybrid`, verify the SRT exists and matches the approved-script alignment.

## Rendered Hook Quality v2

For every current production whose persisted preflight evidence says Hook Quality is required, the review of the **actual rendered MP4** must persist `final_review.metadata.hookQualityReview` with:

- `version: "2.0"`;
- `reviewSource: "rendered_mp4"`;
- `reviewerRole: "independent_reviewer"` — the authoring/editing role must not certify its own hook;
- `reviewedCandidateSha256` matching the exact MP4 bytes;
- `strength`: `weak`, `acceptable`, or `strong`;
- a non-empty rationale;
- at least two opening-specific observations made from the rendered candidate;
- `coldViewer` structured evidence from a context-isolated opening-only review, including `evidenceSource: "rendered_opening_only"`, `contextIsolated: true`, non-empty `inferredTopic`, `inferredClaim`, `continuationReason`, and an `unresolvedReferents` array;
- `mutedHookDirectionConfirmed` derived from that structured cold-viewer evidence, not supplied as an independent self-certifying boolean;
- `visualVoiceAlignment` as `weak` / `acceptable` / `strong`;
- `concretePayoffKind` as `answer`, `result`, `example`, `demonstration`, `evidence`, or `mechanism`;
- `actualPayoffSeconds` measured from when the concrete answer/result/example/evidence actually reaches the viewer;
- non-empty `payoffEvidence` describing that concrete rendered event;
- `payoffBeginsPromptly`.

The cold-viewer review input must contain only the rendered opening evidence and neutral review instructions. Build it with `lib.persian_rendered_review.build_cold_viewer_review_input`, persist it inside the current project as a JSON artifact, and record `metadata.coldViewerReviewInput.path` plus its exact `sha256`. The reviewer result must repeat that digest as `coldViewer.reviewInputSha256`. Final-review validation re-reads the artifact, re-hashes it, rebuilds the canonical allowlisted payload, and rejects hidden authoring context before presentation. Do not expose approved script, hook metadata, scene-plan labels, author rationale, topic labels, or other hidden production context to that reviewer. `contextIsolated: true` is valid only when this persisted input artifact passes the allowlist validator.

Do not count setup/authority phrases such as “research shows” as payoff. Timeline metadata cannot certify rendered comprehension. A weak review, failed muted direction, weak visual/voice alignment, non-concrete payoff, digest mismatch, or payoff after the blocking ceiling may be persisted honestly as failed/revise evidence, but it blocks presentation. Historical v1 artifacts remain readable only as history; new productions must use v2.

## Rendered audio evidence

`checks.audio_spotcheck` must be evidence-backed; `mix_intelligible: true` by itself is never enough. Persist:

- `policyVersion: "1.0"`;
- `measurementSource: "rendered_mp4_plus_mix_policy"`;
- `candidateSha256` matching the exact MP4;
- `outputIntegratedLufs` measured from the rendered MP4;
- `truePeakDbfs` measured from the rendered MP4;
- `narration_present`, `unexpected_silence`, `clipping_detected`, `mix_intelligible`, and `issues`;
- `music_present`.

When music is present, also persist `separationMethod: "source_lufs_plus_render_gain"`, measured `narrationLufs`, measured `musicLufs`, the actual digest-bound `speechMusicGain`, and calculated `speechMusicSeparationLu`. The separation must remain inside the versioned loudness policy; both music that is too loud and music that is too quiet block presentation. When music is intentionally absent, persist a non-empty `musicOmittedReason` instead of inventing separation evidence. Output loudness and true peak/clipping remain final rendered gates even when separation passes.

## Lifecycle and presentation

Persist the normal `final_review` artifact inside the current project with `status: pass`, `recommended_action: present_to_user`, at least four real reviewed frame paths, passing technical/audio/promise/subtitle checks, and `output_path` pointing to the same digest-bound MP4. Set `render_report.final_review_ref` to that exact artifact. Workflow state stores only the validated artifact path/hash and candidate path/hash; it never substitutes prose evidence for the artifact.

The compose checkpoint must be written as `awaiting_human`, never self-approved. Its primary output must be an MP4 inside this project's directory with a 64-character SHA-256 matching the exact file bytes, `delivery_status="final_candidate"`, `human_visual_approval=false`, and `persian_text_verified=false`. Mere MP4 existence is never final-candidate approval.

After final QA is persisted, advance the front-door state only through the code API:

```bash
python -m lib.persian_video_workflow attempt <project-id> --phase final_review
python -m lib.persian_video_workflow complete <project-id> --phase final_review --evidence-json final-review-evidence.json
# final-review-evidence.json contains only: {"final_review_path":"artifacts/final_review.json"}
python -m lib.persian_video_workflow complete <project-id> --phase awaiting_human
```

The final command independently re-reads `checkpoint_compose.json`, resolves the reported render path, refuses a render outside this project, re-hashes the MP4 bytes, requires the validated final review, and only then changes workflow status to `awaiting_human` with `next_phase=null`.

At that point **stop**. Present that exact candidate to the user and wait for explicit approval. Approval and compose completion continue through the existing digest-bound checkpoint protocol; this front-door skill never treats silence, a general goal, or an earlier approval as approval of the candidate.
