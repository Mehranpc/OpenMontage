---
name: persian-video
description: Production-only front door for building a Persian video from approved Persian copy and/or narration audio.
---

# Persian Video

Use this skill only when the user explicitly asks to **make, build, render, continue, or resume a Persian video**.

This skill does not write, translate, improve, or rewrite narration. Text-only Persian writing belongs to separate user/global skills. **Do not create a project for a text-only request**, even if the user mentions `/persian-video` while asking only for narration, rewriting, translation, captions, hooks, or other copy.

The ordered workflow, retry/send-back limits, stock-download ceilings, read isolation, and terminal state are owned by `lib/persian_video_workflow.py`. Do not reproduce or reorder its phase list in prose. Canonical production-stage contracts remain in `pipeline_defs/persian-footage.yaml` and `skills/pipelines/persian-footage/`.

Read scope (#329): during a production, read only the current project, its inputs, and the repo paths listed in the project's `workflow_state.json` under `read_allowlist.repo_paths` (skills, pipeline definition, styles, hook references, Film Type contract, and `schemas/`). `tests/`, `tests/fixtures/` and rehearsal decisions are off-limits: they are a previous run's recorded creative choices, clip picks and review answers, not contracts. A run that copies them is not independent, and its acceptance evidence is void. Artifact shapes come from `schemas/`.

## Production input boundary

A fresh production may start from:

- narration audio whose spoken words are authoritative;
- an approved Persian script whose wording is authoritative;
- both, which is preferred when recorded narration must match approved copy.

"Approved" means the user supplied or selected that Persian wording as the copy to produce. The production pipeline may perform technical normalization allowed by the subtitle contract, but it must not editorially rewrite the wording.
## Start a fresh production

**Before `bootstrap` on a production machine, run `make pre-mac` (#265).** It exits non-zero unless the checkout is clean and its SHA passed the CI rehearsal (`tests/rehearsal`, which drives a recorded run to `awaiting_human`). If it refuses, do not start the run: report its one-line reason. A production run accepts real footage and taste. It is not a way to find pipeline bugs; any bug it finds is first reproduced as a rehearsal scenario, then fixed.

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
python -m lib.persian_video_workflow status <project-id> --json
```

`status` is read-only. Its default output is one operational line with the current
phase, phase elapsed time, wall time versus budget, last written file, and
`progressing`/`idle` (`idle` means no project write for 15 minutes). Use `--json`
when routing by `next_phase` or inspecting telemetry. Before a supported front-door
command admits new active work, before a new durable run-kernel execution starts, and
at safe checkpoints while a durable child is running, the same wall/SLO policy is
enforced. The wall and phase budgets charge only time the run was worked: recorded
human waits and any silence of more than 15 minutes between pipeline commands (with
no durable job running; read-only commands such as `status` do not break it) are
parked time and are not charged (`operational_summary.parked_seconds` /
`charged_wall_seconds`). A run left parked while waiting on a decision or a code fix
therefore does not come back as a budget stop. An overrun persists `status=failed`,
`quality_disposition=needs_decision`, stable budget evidence, current phase/work
identity, and the blocked operation before new expensive work continues. Existing
status/reconciliation paths and external asset-result settlement stay usable so
durable evidence is not lost.
Phase completion keeps the same boundary stop policy. A genuine overrun resumes only
after an explicit budget decision; never bypass the persisted stop.

After a GitHub accounting correction, explicitly revalidate an older persisted stop
before choosing an extension based on its historical amount:

```bash
python -m lib.persian_video_workflow budget-revalidate <project-id>
```

This audits the original stopped instant with current accounting. It releases only a
disproven overrun, preserving the original stop in `budget_stop_revalidations`; genuine
wall or phase overruns remain stopped and require `budget-decision`. It grants no
extension, skips no phase, and resets no window or retry counter. `status` remains
read-only. Repeating a released recovery is a no-op.

## Route only by code state

Read `next_phase` from `status`; do not infer progress from conversation memory, filenames, or an earlier writing session.

- `prepare_inputs` / `align_script_timing` → `prepare-production-inputs.md`
- `plan_scenes_moments` through `render_final_candidate` → `narration-to-persian-video.md`
- `final_review` / `awaiting_human` → `persian-final-review.md`

For short/non-durable agent or review work, measure only the interval that is actually being worked. `work-start` opens the current phase attempt if needed for phase-local editorial/review work; `work-finish` closes the countable causal span. When the agent is genuinely working **between** phase attempts, use `agent_interphase`: it is parented directly to the run and deliberately does not open the next phase attempt early. Close every work span before durable execution, user wait, or phase completion. The phase container itself remains non-counting, so gaps are never relabeled as work:

```bash
python -m lib.persian_video_workflow work-start <project-id> --category <agent_editorial_work|agent_interphase|review_evidence_assembly> --name "<truthful activity>"
# perform only that measured work interval
python -m lib.persian_video_workflow work-finish <project-id> <span-id>
python -m lib.persian_video_workflow complete <project-id> --evidence-json /abs/evidence.json
```

Do not start an explicit work span retrospectively and do not leave one open while waiting. `complete` refuses an open explicit work span.

An agent working **continuously** holds **one** span across that working interval. Do not
open and close a span per tool call: the reasoning between calls is part of the interval
being worked, and leaving it uncovered is what makes measured causal coverage collapse.
The measured run that exposed this recorded 18 spans covering 559s of a 3993s wall while
its own editorial categories summed to 1194s — the work was real, it simply was not
spanned. Close the span when you stop working (durable execution, user wait, phase
completion), not after each command. **This includes the interval between phase attempts.**
A `complete` ends a span because the phase is done — it does not end the work: reading the
next phase's contracts, re-deriving state and preparing its first command is measured agent
work too, and it belongs in an `agent_interphase` span. Leaving it uncovered is the single
largest source of unattributed wall time in an agent-driven run: the L3 run that reached
`awaiting_human` closed one span per phase and still measured **53.8%** coverage over an
8784s wall, because every between-phase interval was unspanned while the work was real. The lower-level `attempt` command remains available for phases whose measurable work is entirely represented by durable jobs.

Explicit spans stay the precise record, but they are no longer the only one. Every
`persian_video_workflow`, `persian_run_kernel` and `persian_delivery_quality` command
logs its start and finish to `.telemetry/command-events.jsonl`, and accounting (policy
2.1) reports the time between two commands at most 5 minutes apart as
`agent_command_activity_seconds`: the agent was observably working at both edges. A
longer silence, or any silence after the run stopped for a person, stays unattributed,
and measured spans always take precedence. So keep driving the run through pipeline
commands rather than long stretches of ad-hoc work, and still open spans for long
thinking or review between commands.

If a session stops without `work-finish` and the actual stop time is unknown, recover the open span before resuming work:

```bash
python -m lib.persian_video_workflow work-abandon <project-id> <span-id> --reason "session interrupted before work-finish"
```

This preserves the span's original start and recovery time with an `abandoned_unverified` outcome, but charges none of the unverified interval as measured work. The wall time remains unattributed. Start a new work span for newly observed work; never use a successful `work-finish` at recovery time to retroactively charge the gap. `work-finish --outcome interrupted` and send-back also abandon an open span on the same terms.

For `acquire_assets`, use the bounded acquisition + durable candidate workspace instead of maintaining a separate selection ledger in chat or generated helper scripts. The normal lifecycle is:

```bash
python -m lib.persian_video_workflow asset-search <project-id> --retry-pass <0-or-1> --request /project/request.json
python -m lib.persian_video_workflow asset-candidate-stage <project-id> --json /project/candidate.json
python -m lib.persian_video_workflow asset-candidate-review <project-id> <candidate-id> --json /project/review.json
python -m lib.persian_video_workflow asset-candidate-reject <project-id> <candidate-id> --category <technical|semantic|editorial> --reason "..."
python -m lib.persian_video_workflow asset-candidate-select <project-id> <visual-event-id> <candidate-id> --rejections-json /project/rejections.json
```

Initial music after early visual recovery (#370): when `reopen-asset-search` was
needed before the first assets checkpoint, finish the scoped visual repair and build
the complete audited manifest first. The normal `assets music search/fetch` front
door then permits the still-missing approved Pixabay instrumental bed. It rechecks
the current plan, selections/reviews and canonical manifest before each operation;
pending/invalid/stale visuals, existing music, earlier completed assets and late
edit-recovery scopes still refuse. This does not clear visual scope, grant time,
reset counters or permit unrelated candidate changes. After a successful fetch,
use its persisted `artifacts/music_track.json` in the manifest overrides and build
the full assets checkpoint; do not fetch again to replace that initial bed.

`asset-result` imports provider/source discoveries into project-local durable state. Candidate identity is provider/source ID + exact source-time window + intended crop; review evidence is immutable for that identity. Overlapping reuse of the same source window is blocked, while distinct non-overlapping windows remain legal. Reviewed alternates remain reusable after send-back without reacquisition/re-review when identity is unchanged.

`asset-search` runs the whole bounded pass — `asset-request` → `direct_clip_search` → `asset-result`, and no arithmetic of its own — as **one durable, measured execution** under the current phase attempt, charged to `provider_network_wait`. Two consequences matter to the operator:

- The pass has a resume identity of *(retry pass, exact request bytes, attempt)*. A session that dies mid-download reconciles the same logical search with `python -m lib.persian_run_kernel status <project-id> <job-id>` instead of re-issuing and re-paying for it. Do not edit the request file after starting; a changed request is refused rather than searched.
- **A pass that fails is released, not left latched.** The durable pass closes its own handshake on every outcome: it settles the request on success, and on a provider failure it releases it — clearing `pending_pass` while leaving `completed_passes` untouched, because an outage discovered nothing and must not spend the retry budget. Retry it with the same pass under a fresh identity:

  ```bash
  python -m lib.persian_video_workflow asset-search <project-id> --retry-pass 0 --request <project>/search-request-0.json --attempt 1
  ```

  If the worker was killed outright and could not release its own pass, release it as the operator — then re-issue with the next `--attempt`:

  ```bash
  python -m lib.persian_video_workflow asset-search-release <project-id> --retry-pass 0 --reason "worker killed mid-download"
  ```

  A busy `pending_pass` is refused by `complete`, so a latched pass is what makes a run unable to finish: neither command is optional when a pass fails.
- The pass **does not advance the phase**. Staging, review, rejection, selection, `assets build-manifest` and `assets write-checkpoint` remain your work, and `complete --phase acquire_assets` is still what advances it. Use `--no-wait` when the session cannot block, then reconcile with `status` as above.

Close a prospectively measured agent work span with `work-finish` before starting durable `asset-search`. After the durable result is reconciled, open a new work span for actual staging/review/selection and close it before a provider execution or human wait. Do not leave one work span covering search, downloads, review, and user waits; abandoned spans remain unverified and cannot be retroactively credited.

A wall-budget extension and a phase-budget decision are separate. Inspect the current `budget_stop` reason and threshold before recording a decision: extending the whole run does not clear an independent phase overrun. Report that distinction before asking for another grant; never reset counters or imply that a grant proves the phase meets its SLO.

### Prepare once, then execute (#360)

During `acquire_assets`, read `status` once and act on `acquisition.preparation`. It lists the blockers by event, the unresolved events, the remaining retry passes and send-backs, the reacquisition scope, the legal operations, and `decisionRequired`. It is derived from state and recorded evidence, and reading it changes nothing. It works at a persisted budget stop too, so you can understand a blocker without extending the run first. `diagnostic_elapsed_seconds` reports how long the read took, separately from the run's clocks.

- Routine recovery on the approved provider inside the existing budget is yours: reuse a reviewed alternate, reject an invalid selection, spend the unspent retry pass, `reconcile-plan` with evidence, or use the permitted scoped send-back. Do not ask the user about these. Ask only when `decisionRequired` is set, or when a change would alter approved creative choices (provider, model, narration, visual direction).
- Before asking for an extension: take a current diagnosis, list the remaining operations and which budget each one charges, and say what is still uncertain. The minimum extension is only permission to pass the current overage, not an estimate of how long the work will take. Say so if execution still needs editorial review.
- To bind a mutation to what you prepared, pass `--expect-readiness <acquisition.readiness.inputsSha256>` to `asset-candidate-select` / `asset-candidate-reject`. If the plan, a selection, a review, the policy or the code revision has changed since then, the command refuses with `STALE_PREPARATION` and writes nothing.
- Running status or build-manifest again on unchanged inputs gives the same diagnosis. Stop re-assessing and carry out the allowed repair, or report the specific guard that blocks it.
- `status.work_spans` separates `live_open_span_ids` from `stop_snapshot_open_span_ids`, which is history recorded with the stop. A snapshot ID that appears in `stop_snapshot_since_finished` is finished, not an accounting bug. Calling `work-finish` again on a finished span returns it unchanged. Finish work whose end you know with `work-finish`. Use `work-abandon` only when the actual end is unknown.

When a parent agent delegates to a production worker, it prepares once. It then hands over one concrete, bounded task, for example "repair `invalidEvents` until `readiness.disposition` is `ready_for_manifest`, then build the manifest and write the assets checkpoint". The task includes that stop condition and asks for the command outcomes plus evidence paths back. The worker stops at the canonical checkpoint, at a real guard, or at an owner gate. Code defects go back to the parent's GitHub branch → PR → CI workflow. A worker never leaves a local code fix behind.

`asset-request` and `asset-result` remain the underlying handshake, and remain correct to use directly only for a provider path `asset-search` cannot take.

`asset-candidate-select` returns `manifestBinding` and `manifestEvidence`; use those exact fields in the canonical `asset_manifest` row. Once asset workspace state exists, `complete --phase acquire_assets` enforces that every workspace-bound visual event has exactly one selected row with matching identity and review evidence. `status.asset_workspace` is the durable source for candidate/reuse/rejection/weak-resolution state. `asset_manifest` remains the canonical selected artifact; the workspace is durable discovery/review history.

For Pixabay Music, do not treat `PIXABAY_API_KEY` as a Music-search credential. If legacy `pixabay_music` web search is blocked by Cloudflare, use the installed `ego-browser` skill for normal browser discovery and the real `Free download` event, save the MP3 inside the current project, then pass the browser-observed CDN URL plus real title/artist/source-page/duration metadata through `pixabay_music` `direct_cdn` mode. This is provider recovery, not permission to invent provenance, bypass anti-bot checks, or switch providers silently. See `docs/PIXABAY_MUSIC.md`.

For `no_copy_preflight`, never write `artifacts/edit_decisions.json` directly. Use the durable convergence workspace through the production front door. The first candidate needs only the immutable stage/preflight flow:

```bash
python -m lib.persian_video_workflow edit-stage <project-id> <base-candidate-id> --json /allowed/edit-decisions.json
python -m lib.persian_video_workflow edit-preflight <project-id> <base-candidate-id>
```

For a diagnostic-only check of the exact same staged candidate, use the supported
read-only front door instead of invoking `lib.persian_preflight` directly:

```bash
python -m lib.persian_video_workflow edit-probe <project-id> <candidate-id>
```

`edit-probe` loads the same workflow hook authority and policy/version pin and calls
the same aggregate preflight oracle as `edit-preflight`, but it does not persist
preflight reports, caches, candidate dispositions, counters, phase completion, or
other durable workflow state. It remains wall-budget guarded because the canonical
oracle may legitimately reach Chromium.

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

Asset-selection recovery is workspace-bound. A recovery draft that changes footage/source-window identity must bind every changed shot to an exact reviewed asset-workspace candidate before `edit-stage` can consume a convergence candidate. Write a project-local binding object such as:

```json
{
  "version": "1.0",
  "shotBindings": [
    {"shotId": "shot-2", "candidateId": "asset-..."}
  ]
}
```

and stage with `--asset-binding-json <project-local-path>`. The candidate id carries immutable provider/source/window/crop/review authority; never infer a new crop or treat a recovery strategy name as review evidence. If no exact reviewed candidate exists, use the bounded `send-back` to `acquire_assets`, review/select the resulting candidate through the asset workspace, rebuild the canonical manifest, and only then promote. Promotion refuses when the manifest selection is not the same identity bound into the edit candidate.

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

Use `agent_interphase` only for prospectively measured agent work between phase executions; unlike phase containers, it counts toward wall coverage without opening the next phase attempt. Each run also pins code revision, Python/platform/hardware facts, initial cache classification, and `.workspace/*.py` count; the terminal performance summary refreshes cache/script counts so late-created state is visible.

Accounting policy `2.0` excludes inferred `phase_residual` spans from measured coverage, including historical residuals. Phase start/end timestamps alone do not prove continuous editorial or review work. Record actual work intervals; preserve gaps as unknown. Existing frozen summaries remain historical evidence. New terminal summaries retain prior summaries in `performance_summary_history`, bind the candidate digest, and show whole-run and `revision_window` accounting separately. A user-directed revision resets `send_backs`, `plan_reconciliations` and attempts for its new budget window; it archives the old values in `revision_cycle_archive`. Report counts and phase SLO overruns from `performance_summary.whole_run`, never from the live counters (#251).

Before `awaiting_human`, the front door reconciles durable execution envelopes through the kernel, then settles phase telemetry, then freezes the summary. Pending jobs or failed telemetry reporting block presentation without discarding successful media. Retry reconciliation for the same identity; never rerender just to repair reporting.

A child process exit code of zero is **not** semantic success. Tool/helper commands run through this kernel must persist their normalized JSON result to the path supplied in `OPENMONTAGE_DURABLE_RESULT_PATH`; a result with `success=false` blocks workflow advancement even when the process exits normally. If expensive execution succeeded but workflow commit/reporting later fails, reuse the same logical `idempotence_key` and reconcile/commit the durable job rather than rerunning the expensive stage. On an open phase attempt the kernel resolves that key back to the original durable job even if a restarted caller presents a fresh job id; the returned `jobId` is authoritative. Never mint a new idempotence key merely because the caller/session crashed.

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

**Name the hook's first proof in the plan (#262).** Put `hook_first_proof` in the `plan_scenes_moments` evidence: `{"kind": "evidence|result|example|demonstration|answer|mechanism", "anchorText": "<the spoken proof phrase>"}`. The workflow times that phrase on the approved-script word timings that `alignment-commit` writes to `artifacts/script-word-timings.json` (#290); do not write that file yourself. For an automatic hook it refuses `[HOOK_PROOF_LATE]` when the phrase lands after 6s, before any footage is bought. The user decides then; `hook-override` is valid at `plan_scenes_moments` for exactly this answer. Name `hook_viewer_value` and `hook_semantic_tension` the same way (`{"anchorText": "<spoken phrase>", "evidence": "..."}`). They must be spoken by 3.0s and 4.0s; the plan refuses `[HOOK_VALUE_LATE]` / `[HOOK_TENSION_LATE]` for every hook, user-owned included, because the edit precheck would (#298).

`hook-override` is valid at an active `plan_scenes_moments` (the proof gate above), or at an active `no_copy_preflight`, either in the user-directed revision opened by `send-back`, or before any candidate has been rendered. The second case is for when the preflight hook-quality gate hands the decision to the user (for example, first proof after 6s on an automatic hook) and the user answers "record this sentence as my hook": run `hook-override` with that exact sentence in the same run, then re-run the edit preflight. Do not start a fresh run or re-download assets for it. It archives the superseded automatic decision and makes the new copy `user_supplied` and authoritative; do not simulate this by calling automatic selection again or editing workflow JSON.

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
