# Final Candidate Protocol — Persian Footage

## One human gate

Run autonomously from supplied input to one complete rendered **final candidate**.
Do not ask the user to approve idea, queries, assets, typography boxes, or subject
regions separately. Compose first writes `awaiting_human` with
`delivery_status: final_candidate`, `human_visual_approval: false`, and
`persian_text_verified: false`. After rendering, compute `outputs[0].sha256` from the
actual MP4 bytes; checkpointing recomputes it and refuses a mismatch. Only explicit
approval of that exact path and digest may rewrite compose as `completed` with
`human_approved: true`, `delivery_status: approved`, and
`human_visual_approval: true`. Preserve the candidate output entry byte-for-byte and
write `metadata.approval_record` with `source: explicit_user_response`,
`candidate_path`, and `candidate_sha256`. A changed render is a new candidate.

A prompt, continuation goal, retry instruction, agent inspection, successful test,
or silence is not visual approval. If narration audio is already supplied, continue;
waiting for missing audio is an input dependency, not a visual gate.

## Joint footage/type planning

Plan semantic beats first, then solve footage and typography together. Store
`scene_plan.metadata.display_requirements` by beat:

- `exact`: immutable user-mandated display copy, such as an exact opening hook;
- `adaptable`: up to three shorter display candidates grounded in the same narration;
- `none`: no on-screen moment for that beat.

Inspect candidate footage at the start, middle, and end of its intended cropped
window. Estimate conservative normalized subject/action envelopes across camera
motion. These `avoidRegions` are machine-estimated geometry, not human approval;
`[]` means the whole window was inspected and found clear.

Jointly evaluate semantic relevance, subject continuity, negative space, copy mode,
placement, legal Film Type ladder rung, reading dwell, cut alignment, contrast, and
watermark feasibility. Exact copy stays exact. Reject a candidate when truthful
regions block all layouts—never tighten a region because the planner wants its zone.
Prefer one compatible shot long enough for the moment instead of extending a fixed
layout across incompatible cuts.

Persist `edit_decisions` only by promoting the exact draft whose aggregate preflight report passed. Failed candidates stay under project-local `.drafts/` and `.preflight/`; they never overwrite the canonical artifact or create a completed edit checkpoint. Promotion is SHA-256 bound to the probed draft and writes `checkpoint_edit.json` only after the same digest passes.

Preflight also refuses overlapping reuse of the same source-time window across shots; visibly repeating the same footage is not an acceptable default. Distinct non-overlapping windows from one longer source remain valid. Narrated projects must carry a measurable music bed: a path/licence record alone is insufficient when the file is effectively silent. The source bed must clear the conservative audibility floor before browser preflight, and the ducked bed must also remain within the permitted loudness gap from narration; a technically present but perceptually absent mix is a failure. Normalize or replace near-silent music and use the canonical mix levels rather than compensating with extreme renderer gain.

## Bounded work

No-copy edit/layout convergence is bounded by the durable candidate workspace, not by an agent-maintained probe count. The current workflow derives the per-revision-cycle global candidate ceiling from `1 + max_revisions_per_stage`, while each recovery class keeps its own policy ceiling. A base candidate counts toward the global ceiling; every recovery child records its parent, diagnostic cause, strategy, mutation surface, changed fields/scopes, dependency digests, cache hits, diagnostics, and disposition.

At a class or global limit, stop with the workspace's structured `needs_revision` report. Do not manufacture another `probe_*` file, helper Python script, or parallel retry ledger. A new explicit user goal may authorize one fresh bounded cycle through `python -m lib.persian_video_workflow send-back <project-id> <target-phase> --reason "..." --user-directed-revision`; this records prior history and starts the next revision cycle without editing workflow JSON or counters by hand. Asset-acquisition budgets remain separate and are not silently expanded by edit convergence.

## No-copy preflight

For front-door production use the project convergence lifecycle. Stage the base candidate normally; a recovery child must declare explicit ancestry plus the diagnostic/strategy/mutation it is attempting:

```bash
python -m lib.persian_video_workflow edit-stage <project-id> <base-id> --json /allowed/edit-decisions.json
python -m lib.persian_video_workflow edit-preflight <project-id> <base-id>

python -m lib.persian_video_workflow edit-stage <project-id> <child-id> --json /allowed/revised-edit.json \
  --parent <base-id> \
  --diagnostic-code <blocking-code> \
  --recovery-class <recovery-class> \
  --strategy <allowed-strategy> \
  --changed-field <owned-mutation-field>
python -m lib.persian_video_workflow edit-preflight <project-id> <child-id>
python -m lib.persian_video_workflow edit-compare <project-id> <base-id> <child-id>
python -m lib.persian_video_workflow edit-promote <project-id> <passing-id>
```

`python -m lib.persian_video_workflow status <project-id>` exposes candidate lifecycle and structured exhaustion. Unchanged retention/hook/browser evidence may be reused only when its declared dependency digest is identical; a whole-report cache hit is tracked separately from component hits. Cheap deterministic blockers run before browser-heavy geometry. Promotion is bound to both the staged edit digest and the persisted preflight-report identity, so changing either after preflight blocks promotion. The legacy `recovery-attempt` command remains a compatibility/debug primitive; normal convergence must not duplicate workspace budget accounting through it.

If a versioned policy or preflight implementation changes after an edit candidate has already been promoted, do not spend another editorial convergence candidate merely to refresh evidence. Rewind through the normal workflow to `no_copy_preflight`, then use `edit-preflight <project-id> <promoted-id> --recertify-promoted` only when the promoted draft, candidate manifest, and canonical `artifacts/edit_decisions.json` still have the same artifact digest. This opt-in archives the prior certification, recomputes dependency-sensitive evidence under the current policy/code identity, and leaves the convergence candidate count unchanged. It is not an edit mutation, a budget reset, or permission to recertify different bytes. Promote the same digest again idempotently after the refreshed preflight passes.

`lib.persian_preflight` remains the lower-level diagnostic CLI when a standalone report is needed. It runs the real audits and Film Type browser measurement while validating media paths without copying them. It persists an aggregate report on both pass and refusal when `--output` is supplied. It also runs `lib.persian_retention.audit_persian_retention`:
the first three seconds need a second visual event or pattern interrupt, uncovered visual
intervals are refused, long uninterrupted events and long text-only endings are reported,
and cut grammar is recorded. The numeric ~8-10s long-shot range is a retention-risk
warning, not misrepresented as a universal law. It writes no checkpoint and leaves no persistent staging.
Never call `PersianCompose._build_props` directly from an agent script and never use
`renders/.prep` for probes. Run `persian_compose` once for the accepted edit; normal
render staging must be cleaned on every exit unless explicit debug retention was
requested.

## Post-render review package

Present the complete MP4 and its sha256 plus entry/stable/exit frames for every
moment, both sides of crossed cuts, warnings for geometry/contrast/watermark/luminance/
captions/subtitles (including burned-caption entry/mid/exit samples when enabled), and an optional separate debug sheet with region boxes. The non-human review
package also carries the measured retention audit plus `post_render_motion_qa`, muted-viewer
comprehension, cut rhythm, caption readability, strongest scene, weakest scene, hook
strength, and resolution strength. Timeline code measures authored cadence; the motion QA
samples the actual MP4 at 2fps after a tiny grayscale downscale and measures consecutive
pixel deltas. A roughly eight-second near-frozen stretch is an advisory; a roughly ten-second
near-frozen stretch blocks delivery. These thresholds are deliberately conservative and do
not pretend to score subtle creative motion. The reviewer states semantic judgements instead
of pretending they were inferred from timestamps. Persist a schema-valid `final_review`
artifact inside the project and link it from `render_report.final_review_ref`; the workflow
rehashes that review artifact and the MP4 before entering `awaiting_human`. Burned/hybrid
captions retain at least entry/mid/exit frame paths in
`render_report.caption_verification_frames`, and the generic visual spotcheck retains at
least four real frame paths. The user reviews once. On rejection, revise only named scenes
and produce a new candidate.
