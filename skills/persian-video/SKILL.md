---
name: persian-video
description: Production-only front door for building a Persian video from approved Persian copy and/or narration audio.
---

# Persian Video

Use this skill only when the user explicitly asks to **make, build, render, continue, or resume a Persian video**.

This skill does not write, translate, improve, or rewrite narration. Text-only Persian writing belongs to separate user/global skills. **Do not create a project for a text-only request**, even if the user mentions `/persian-video` while asking only for narration, rewriting, translation, captions, hooks, or other copy.

The ordered workflow, retry/send-back limits, stock-download ceilings, read isolation, and terminal state are owned by `lib/persian_video_workflow.py`. Do not reproduce or reorder its phase list in prose. Canonical production-stage contracts remain in `pipeline_defs/persian-footage.yaml` and `skills/pipelines/persian-footage/`.

## Production input boundary

A fresh production may start from:

- narration audio whose spoken words are authoritative;
- an approved Persian script whose wording is authoritative;
- both, which is preferred when recorded narration must match approved copy.

"Approved" means the user supplied or selected that Persian wording as the copy to produce. The production pipeline may perform technical normalization allowed by the subtitle contract, but it must not editorially rewrite the wording.
## Start a fresh production

Create a genuinely new project only after video-production intent is explicit:

```bash
python -m lib.persian_video_workflow bootstrap --title "Title" --narration /abs/narration.wav
python -m lib.persian_video_workflow bootstrap --title "Title" --approved-script "متن تأییدشده"
printf '%s' "$APPROVED_SCRIPT" | python -m lib.persian_video_workflow bootstrap --title "Title" --approved-script-file -
python -m lib.persian_video_workflow bootstrap --title "Title" --narration /abs/narration.wav --approved-script-file /abs/approved-script.txt
```

Raw notes, source articles, English articles, and unapproved draft copy are intentionally not valid bootstrap inputs. Author or revise those outside this production skill first.

Repository root is never a production scratch directory. Do not create `tmp_*_approved_script.txt`, `probe_*`, generated helper scripts, or debug files beside repository code. For agent-held approved copy, pass the text directly or use `--approved-script-file -`; bootstrap persists the authoritative bytes under the new project. Existing user-owned source files may be read only from outside the repository.

Bootstrap creates `projects/<new-id>/`, copies the approved production inputs into that project, records hash-bound workflow state, and opens that project's Backlot board. An existing project directory is a hard refusal, never a resume shortcut.

If production starts from an approved script without audio, remain in input preparation. When recorded narration or an explicitly approved TTS result exists, attach it to the same project:

```bash
python -m lib.persian_video_workflow attach-narration <project-id> /abs/narration.wav
```

For a later session, resume the same bounded state without resetting durable counters:

```bash
python -m lib.persian_video_workflow resume <project-id>
python -m lib.persian_video_workflow status <project-id>
```
## Route only by code state

Read `next_phase` from `status`; do not infer progress from conversation memory, filenames, or an earlier writing session.

- `prepare_inputs` / `align_script_timing` → `prepare-production-inputs.md`
- `plan_scenes_moments` through `render_final_candidate` → `narration-to-persian-video.md`
- `final_review` / `awaiting_human` → `persian-final-review.md`

For short/non-durable agent or review work, measure only the interval that is actually being worked. `work-start` opens the current phase attempt if needed; `work-finish` closes the countable causal span. Close it before durable execution, user wait, or phase completion. The phase container itself remains non-counting, so gaps are never relabeled as work:

```bash
python -m lib.persian_video_workflow work-start <project-id> --category <agent_editorial_work|review_evidence_assembly> --name "<truthful activity>"
# perform only that measured work interval
python -m lib.persian_video_workflow work-finish <project-id> <span-id>
python -m lib.persian_video_workflow complete <project-id> --evidence-json /abs/evidence.json
```

Do not start an explicit work span retrospectively and do not leave one open while waiting. `complete` refuses an open explicit work span. The lower-level `attempt` command remains available for phases whose measurable work is entirely represented by durable jobs.

For `acquire_assets`, use the bounded acquisition + durable candidate workspace instead of maintaining a separate selection ledger in chat or generated helper scripts. The normal lifecycle is:

```bash
python -m lib.persian_video_workflow asset-request <project-id> --retry-pass <0-or-1> --json /project/request.json
# Execute direct_clip_search with the bounded request; persist its normalized ToolResult data.
python -m lib.persian_video_workflow asset-result <project-id> --retry-pass <0-or-1> --json /project/result.json
python -m lib.persian_video_workflow asset-candidate-stage <project-id> --json /project/candidate.json
python -m lib.persian_video_workflow asset-candidate-review <project-id> <candidate-id> --json /project/review.json
python -m lib.persian_video_workflow asset-candidate-reject <project-id> <candidate-id> --category <technical|semantic|editorial> --reason "..."
python -m lib.persian_video_workflow asset-candidate-select <project-id> <visual-event-id> <candidate-id> --rejections-json /project/rejections.json
```

`asset-result` imports provider/source discoveries into project-local durable state. Candidate identity is provider/source ID + exact source-time window + intended crop; review evidence is immutable for that identity. Overlapping reuse of the same source window is blocked, while distinct non-overlapping windows remain legal. Reviewed alternates remain reusable after send-back without reacquisition/re-review when identity is unchanged.

`asset-candidate-select` returns `manifestBinding` and `manifestEvidence`; use those exact fields in the canonical `asset_manifest` row. Once asset workspace state exists, `complete --phase acquire_assets` enforces that every workspace-bound visual event has exactly one selected row with matching identity and review evidence. `status.asset_workspace` is the durable source for candidate/reuse/rejection/weak-resolution state. `asset_manifest` remains the canonical selected artifact; the workspace is durable discovery/review history.

For Pixabay Music, do not treat `PIXABAY_API_KEY` as a Music-search credential. If legacy `pixabay_music` web search is blocked by Cloudflare, use the installed `ego-browser` skill for normal browser discovery and the real `Free download` event, save the MP3 inside the current project, then pass the browser-observed CDN URL plus real title/artist/source-page/duration metadata through `pixabay_music` `direct_cdn` mode. This is provider recovery, not permission to invent provenance, bypass anti-bot checks, or switch providers silently. See `docs/PIXABAY_MUSIC.md`.

For `no_copy_preflight`, never write `artifacts/edit_decisions.json` directly. Use the durable convergence workspace through the production front door. The first candidate needs only the immutable stage/preflight flow:

```bash
python -m lib.persian_video_workflow edit-stage <project-id> <base-candidate-id> --json /allowed/edit-decisions.json
python -m lib.persian_video_workflow edit-preflight <project-id> <base-candidate-id>
```

When preflight returns a named recoverable diagnostic, the agent chooses one permitted strategy and stages exactly one bounded child candidate with explicit ancestry and mutation metadata:

```bash
python -m lib.persian_video_workflow edit-stage <project-id> <candidate-id> --json /allowed/revised-edit.json \
  --parent <parent-candidate-id> \
  --diagnostic-code <blocking-code> \
  --recovery-class <recovery-class> \
  --strategy <allowed-strategy> \
  --changed-field <owned-mutation-field>
python -m lib.persian_video_workflow edit-preflight <project-id> <candidate-id>
python -m lib.persian_video_workflow edit-compare <project-id> <parent-candidate-id> <candidate-id>
```

`status` exposes the durable convergence state, candidate IDs, promoted candidate, and any structured `needs_revision` stop. Candidate ceilings come from workflow state and recovery policy; never maintain a second probe counter in chat or a helper script. The workspace rejects out-of-surface mutations, reuses only dependency-identical preflight components, runs browser-heavy checks only after cheap blockers pass, and keeps failed candidates non-canonical. The lower-level `recovery-attempt` command is compatibility/debug bookkeeping and is **not** part of normal edit convergence. Do not create ad hoc `probe_*` artifacts or generated Python orchestration scripts.

If browser preflight reports `ASSET_SELECTION_HARD_REGION_COLLISION`, its `details.momentId` and `details.shotIds` identify reviewed hard regions that blocked measured placement. The same browser run confirms that the moment fits when only subject obstacles are omitted; it never persists that counterfactual. Keep the approved moment copy and hard regions. Reuse a reviewed alternate with truthful geometry if available; otherwise use the existing bounded `send-back` to `acquire_assets` and its shared acquisition budget. Scene planning and asset selection cannot certify this fit earlier: exact on-screen moments first exist in the edit draft, after selected-window subject review. A width-only or explicit-placement refusal remains a layout issue, not evidence that the asset is incompatible.

Promote only the exact passing candidate, then complete the phase:

```bash
python -m lib.persian_video_workflow edit-promote <project-id> <candidate-id>
printf '{"attempt_id":"<candidate-id>"}' > /tmp/preflight-evidence.json
python -m lib.persian_video_workflow complete <project-id> --phase no_copy_preflight --evidence-json /tmp/preflight-evidence.json
```

Long-running current-phase commands use the production run kernel. It owns the phase-attempt binding, durable job identity, process outcome, semantic result, reporting outcome, and workflow commit. For normal single-process production work, prefer the bounded one-shot `run` command so reconciliation happens locally as soon as the durable child finishes instead of waiting on an agent round-trip. Use `--` before the child command:

```bash
python -m lib.persian_run_kernel run <project-id> <job-id> --phase <next-phase> --idempotence-key <key> --telemetry-category <category> --evidence-json /abs/evidence.json --timeout-seconds <bounded-seconds> -- <command> [args...]
```

`run` is exactly the existing durable `start → reconcile → commit` lifecycle under one bounded local wait. If the caller/session must remain asynchronous, or a prior one-shot wait timed out, use the same durable identity with the lower-level recovery controls:

```bash
python -m lib.persian_run_kernel start <project-id> <job-id> --phase <next-phase> --idempotence-key <key> --telemetry-category <category> -- <command> [args...]
python -m lib.persian_run_kernel status <project-id> <job-id>
python -m lib.persian_run_kernel commit <project-id> <job-id> --evidence-json /abs/evidence.json
```

Every durable command must use the narrowest truthful causal category. Use `provider_network_wait` for provider/API-bound work, `machine_local_execution` for local CPU/GPU/ffmpeg/MLX work, and `browser_render_execution` for Chromium/Remotion/browser-heavy execution. The workflow persists one `causal_trace_id`; durable jobs become child spans of their phase attempt, and first terminal reconciliation is recorded separately as `accounting_reconciliation`. Do not relabel a whole render phase as renderer time: only the durable browser/render span is renderer time.

`status.time_accounting` keeps real wall time as the top-level metric and reports `causal_coverage_percent`, category durations, explicit concurrency, and any remaining `unattributed_wall_seconds`. Unattributed time is an instrumentation diagnostic, not a bucket to silently assign to providers or editorial work.

Accounting policy `2.0` excludes inferred `phase_residual` spans from measured coverage, including historical residuals. Phase start/end timestamps alone do not prove continuous editorial or review work. Record actual work intervals; preserve gaps as unknown. Existing frozen summaries remain historical evidence. New terminal summaries retain prior summaries in `performance_summary_history`, bind the candidate digest, and show whole-run and `revision_window` accounting separately.

Before `awaiting_human`, the front door reconciles durable execution envelopes through the kernel, then settles phase telemetry, then freezes the summary. Pending jobs or failed telemetry reporting block presentation without discarding successful media. Retry reconciliation for the same identity; never rerender just to repair reporting.

A child process exit code of zero is **not** semantic success. Tool/helper commands run through this kernel must persist their normalized JSON result to the path supplied in `OPENMONTAGE_DURABLE_RESULT_PATH`; a result with `success=false` blocks workflow advancement even when the process exits normally. If expensive execution succeeded but workflow commit/reporting later fails, retry `commit` for the same job rather than rerunning the expensive stage.

For `render_opening_candidate`, `render_final_candidate`, and `master_final_candidate`, direct `persian_video_workflow complete` is refused. Execute the operation through the run kernel and commit that same job. The child semantic result must include `{"success":true,"data":{"output_path":"/absolute/project/output.mp4","output_sha256":"<exact 64-character digest>"}}`. On commit, the workflow re-hashes the project-local output and compares it with the job result and phase evidence (`opening_candidate_sha256`, `output_sha256`, or `candidateSha256`, respectively). The full render phase evidence must now include `output_sha256`. Preserve the durable job identity when retrying a failed commit; never re-render successful bytes to repair reporting. The canonical child command is `python -m lib.persian_media_job <project-id> --phase <render_opening_candidate|render_final_candidate|master_final_candidate>`. Run it through one-shot execution; for example:

```bash
python -m lib.persian_run_kernel run <project-id> <job-id> \
  --phase render_final_candidate \
  --idempotence-key <job-id> \
  --telemetry-category browser_render_execution \
  -- python -m lib.persian_media_job <project-id> --phase render_final_candidate
```

Use `render_opening_candidate` for the opening and `machine_local_execution` for mastering. The child writes exact output identity and phase evidence to the kernel semantic-result path, so `--evidence-json` is unnecessary for these three phases. Keep the same job id when reconciling a successful run after reporting/commit failure. The synthetic local E2E harness has an explicitly labelled inline fixture adapter so its monkeypatched tools remain testable; it is not the production execution route.

The lower-level `persian_video_workflow job-start/job-status` commands remain compatibility/debug primitives. Normal production should use the run-kernel commands above so execution truth and workflow advancement stay bound to one durable envelope.

If a review requires going backward, use `send-back`; never edit `next_phase` by hand. The code preserves attempt history and enforces the manifest's send-back ceiling.

If explicit new user feedback identifies defects in a rendered candidate after that automatic ceiling is exhausted, use `python -m lib.persian_video_workflow send-back <project-id> <target-phase> --reason "..." --user-directed-revision` to open one fresh bounded revision cycle. The workflow records the old counters, archives invalid downstream checkpoints, and starts a fresh wall-time window; never reset counters or workflow JSON by hand.

If that explicit user feedback also changes a hook that was previously selected automatically, bind the new human-authored wording before staging the revised edit:

```bash
python -m lib.persian_video_workflow hook-override <project-id> --text "هوک تأییدشدهٔ جدید" --reason "Explicit user revision after rendered review"
```

`hook-override` is valid only in the active `no_copy_preflight` user-directed revision opened by `send-back`. It archives the superseded automatic decision and makes the new copy `user_supplied` and authoritative; do not simulate this by calling automatic selection again or editing workflow JSON.

Before reading any path not already opened by the current tool call, enforce project isolation:

```bash
python -m lib.persian_video_workflow guard-read <project-id> /absolute/path
```

Sibling `projects/<other-id>/` artifacts, checkpoints, timings, props, and renders are forbidden. The bootstrap copies initial production inputs into the current project so later stages do not depend on an external article, writing workspace, or another project.
## Canonical production contracts

Always follow these sources rather than restating their rules here:

- `pipeline_defs/persian-footage.yaml` — canonical stage/artifact contracts.
- `skills/pipelines/persian-footage/executive-producer.md` — stage execution and delegation.
- `skills/pipelines/persian-footage/script-director.md` — technical Persian script validation; in this front door, authoritative copy is preserved rather than newly authored.
- `skills/pipelines/persian-footage/subtitle-alignment.md` — approved-script/timing authority boundary.
- `skills/pipelines/persian-footage/hook-quality.md` — evidence-backed short-form hook quality, preflight recovery classes, rendered-hook review, and observational post-publish calibration.
- `skills/pipelines/persian-footage/asset-director.md` — bounded acquisition plus durable Asset Candidate Workspace review/selection and canonical manifest binding.
- `skills/pipelines/persian-footage/final-candidate-protocol.md` — no-copy preflight and candidate lifecycle.
- `skills/meta/checkpoint-protocol.md` — checkpoint persistence and approval protocol.

The front-door workflow terminates only after code verifies a real `compose` checkpoint with `status="awaiting_human"`, an unapproved `final_candidate`, a render path inside the current project, and a SHA-256 matching the exact MP4 bytes. At that point stop and wait for explicit user approval; do not continue to compose completion on your own.

After the user explicitly approves that exact candidate, first rewrite the compose checkpoint through the checkpoint protocol with `status="completed"` and `human_approved=True`, preserving the exact path/SHA approval provenance. Then run `python -m lib.persian_video_workflow reconcile-approval <project-id>`. This reconciliation is mandatory: it digest-checks the approved bytes again, records explicit human-idle telemetry, freezes the terminal performance summary, and moves canonical workflow state from `awaiting_human` to `completed`. Never edit workflow JSON by hand.
