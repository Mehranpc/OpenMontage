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

Persist `edit_decisions` once, only after the entire edit passes preflight. Failed
candidates stay in memory and never create checkpoint history.

## Bounded work

Try at most three footage/layout candidates per beat and twenty probes per video.
At the limit: choose a clearer ranked alternate; shorten only adaptable display copy;
omit a nonessential moment while preserving narration; source a compatible shot for
exact copy; otherwise return one structured blocker. A new user goal may authorize
one new bounded cycle but does not approve visuals.

## No-copy preflight

Use:

```bash
python -m lib.persian_preflight path/to/checkpoint_edit.json
```

It runs the real audits and Film Type browser measurement while validating media
paths without copying them. It also runs `lib.persian_retention.audit_persian_retention`:
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
package also carries the measured retention audit plus muted-viewer comprehension, cut
rhythm, caption readability, strongest scene, weakest scene, hook strength, and resolution
strength. Timeline code measures cadence; the reviewer states semantic judgements instead
of pretending they were inferred from timestamps. Persist a schema-valid `final_review`
artifact inside the project and link it from `render_report.final_review_ref`; the workflow
rehashes that review artifact and the MP4 before entering `awaiting_human`. Burned/hybrid
captions retain at least entry/mid/exit frame paths in
`render_report.caption_verification_frames`, and the generic visual spotcheck retains at
least four real frame paths. The user reviews once. On rejection, revise only named scenes
and produce a new candidate.
