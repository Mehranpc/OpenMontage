# P4 Stabilization & Fast Verification Architecture v1

Status: Proposed

Related tracking: #107 (P4 acceptance umbrella), #138 (failed-shadow stabilization evidence)

## 1. Decision summary

P4 development must stop using a full production/shadow video run as the normal mechanism for discovering the next engineering defect.

During stabilization, failures must first be reproduced and closed in fast, deterministic verification layers. Full cold production shadow runs are reserved for final acceptance after the stabilization gate is green.

The failed shadow project `p4-shadow-first-date-first-text-2cc3664-20260925-000753` remains immutable evidence. It is not resumed, migrated, or retroactively rewritten.

Until the Stabilization Gate in this document is satisfied, **no fresh full P4 shadow run may be started solely to discover the next failure**.

## 2. Why this spec exists

The P4 shadow recorded under #107/#138 exposed a feedback-loop problem rather than one isolated defect:

- the run reached `needs_revision` / `needs_human_editorial_revision` with `global_candidate_budget_exhausted` before render acceptance;
- hard-region placement infeasibility was discovered only after expensive browser preflight and candidate consumption;
- the standalone diagnostic probe and official edit preflight did not share equivalent authority context;
- edit recovery could stage source windows that were not durably reviewed in the asset workspace;
- in-phase work could continue for hours because wall/SLO enforcement occurred at phase boundaries rather than throughout active execution.

The failed run recorded approximately `32286.909s` wall time against the `2700s` P4 target, with `41.154%` causal coverage and `18999.702s` unattributed time. This is useful failure evidence, but it is not an acceptable recurring debugging loop.

The goal of this spec is to make the next engineering failure cheap to reproduce, cheap to localize, and hard to hide.

## 3. Goals

1. Reproduce each known #138 failure without executing a full video workflow.
2. Establish one authoritative preflight implementation and make diagnostic probes reuse it.
3. Run deterministic and inexpensive checks before browser, ffmpeg, candidate consumption, durable render jobs, or full workflow execution.
4. Make asset/edit identity an invariant enforced by durable workspace evidence rather than a convention encoded in recovery strategy names.
5. Enforce execution budgets while work is in progress, not only when a phase boundary is crossed.
6. Create a verification pyramid in which a full production shadow is the last acceptance layer, not the first debugging layer.
7. Preserve GitHub CI as the primary reproducible verification and evidence surface.
8. Stop same-class defects from creating an unbounded chain of new tracking issues during stabilization.

## 4. Non-goals

This spec does not:

- change approved narration or approved copy;
- weaken hard-region truthfulness or safe-placement rules;
- increase candidate, revision, or asset budgets to make failures disappear;
- change render acceptance criteria or the P4 acceptance SLOs owned by #107;
- mark browser/render behavior verified when only a synthetic test passed;
- resume or migrate the failed shadow project;
- backfill or rewrite historical telemetry;
- replace the final fresh cold P4 acceptance run with fixture tests;
- permit ad-hoc project-local scripts as a substitute for supported CLI/workflow behavior.

## 5. Required architecture

### 5.1 Failure fixtures are first-class verification inputs

Every known #138 failure must have a minimal deterministic fixture that captures only the authoritative state required to reproduce it.

A fixture may include, as applicable:

- scene/moment identity and timing;
- display-copy mode and exact/adaptable text required by the gate;
- canonical asset-workspace candidate identity;
- exact source id, source window, crop/transform identity, and immutable review evidence;
- selected asset-manifest identity;
- reviewed subject/hard regions;
- hook authority and pinned policy context;
- edit draft fields needed by the gate;
- expected blocking diagnostic, stage, and recovery route.

Fixtures must not silently invent missing authority. If a production fact is required but not present, the fixture must fail construction or explicitly model the missing-authority failure.

Downloaded production media is not required in L0/L1 fixtures unless the behavior cannot be represented faithfully without it. Media-dependent behavior belongs in L2 targeted smoke tests.

A regression fixture derived from a failed production run is versioned test evidence. Historical source evidence must remain immutable.

### 5.2 One canonical preflight oracle

There must be one canonical implementation for edit-preflight policy decisions.

Any read-only diagnostic interface (`edit-probe` or equivalent) must call the same canonical validator with the same workflow authority context used by official `edit-preflight`, including at minimum:

- hook authority (`user_supplied` when applicable);
- policy/version pin;
- asset/manifest authority;
- reviewed subject-region authority;
- relevant format/design profile context.

The probe may change presentation but must not implement an independent approximation of blocking policy.

A read-only probe must have zero durable side effects:

- no candidate creation or candidate-counter increment;
- no revision-budget consumption;
- no ledger mutation;
- no phase completion;
- no asset selection mutation;
- no durable render/compose job;
- no workflow outcome transition except an explicit read-only diagnostic result returned to the caller.

For the same canonical input and authority context, probe and official preflight must return the same blocking diagnostic set. Advisory formatting may differ only where explicitly documented and tested.

### 5.3 Cheap-before-expensive ordering

Verification order is a contract:

1. schema/state/authority invariants;
2. deterministic geometry and policy checks;
3. fixture/CLI integration;
4. targeted browser/ffmpeg/media smoke when required;
5. durable candidate/render workflow;
6. full cold production acceptance.

A later, more expensive layer must not be used to discover a condition that an earlier authoritative layer can prove deterministically.

Passing a cheap pre-check never claims that the expensive layer will pass. A cheap pre-check may reject only conditions it can prove invalid. Uncertain cases continue to the authoritative downstream measurement.

### 5.4 Workspace-bound asset/edit identity

Edit recovery must not manufacture a new asset identity merely by changing shot fields.

For `reuse_reviewed_non_overlapping_source_window`, `reuse_reviewed_existing_candidate`, or any semantically equivalent strategy:

- the edit operation must reference a durable asset-workspace candidate id;
- that candidate must contain immutable review evidence for the exact source id, exact source window, and crop/transform identity being used;
- the selected/canonical asset manifest must be rebound through the supported asset authority path when the chosen identity changes;
- asset-dependent scene metadata must be derived from or validated against that authoritative candidate rather than independently widened field by field;
- if the exact identity is absent from durable reviewed asset state, `edit-stage` must refuse it before candidate consumption and route through the bounded send-back to `acquire_assets`;
- promotion must refuse when manifest identity and edit-shot identity differ.

Strategy names are not evidence. Durable reviewed workspace state is evidence.

The implementation should prefer an operation-shaped interface such as “replace/reuse shot from reviewed asset candidate” over a broad permission to mutate unrelated asset-dependent fields independently.

### 5.5 Deterministic hard-region feasibility pre-check

A render-independent geometry check must reject placement only when infeasibility is provable from authoritative inputs such as:

- reviewed hard `avoidRegions`;
- format safe area;
- canonical Film Type minimum measured footprint / allowed placement envelope;
- exact/adaptable display-copy geometry when required by the rule.

The check must run early enough to prevent known-impossible candidates from consuming edit-candidate budget. It must be usable during or immediately after subject-region review when sufficient copy/layout authority exists, and again at edit staging as a final cheap guard.

A deterministic rejection must preserve the existing blocking class when appropriate (`ASSET_SELECTION_HARD_REGION_COLLISION`) and identify the source as `details.stage=geometric_precheck` or an equivalent stable machine-readable field.

Browser measurement remains authoritative for cases that are not provably impossible. The pre-check must not create false “safe” results by treating missing evidence as free space.

### 5.6 In-phase wall/SLO watchdog

Wall-budget enforcement must apply while a phase is active.

At minimum the budget must be evaluated:

- at every supported workflow front-door command before expensive work starts;
- at safe checkpoints inside potentially long orchestration paths;
- before and after external Chromium/ffmpeg/render subprocess boundaries where the workflow can regain control.

Long-running child work must receive a bounded deadline/timeout when the underlying interface supports it. A parent must not start new expensive work after its effective deadline has expired.

When the workflow exceeds its wall/SLO budget, it must persist an actionable state such as:

- `needs_decision`;
- stable reason `wall_budget_exceeded`;
- phase/work-span identity;
- elapsed/budget timing evidence;
- active operation/subprocess evidence when available.

The stop must not consume a new edit candidate merely to record the timeout.

Read-only status may diagnose stale/over-budget state, but status polling is not a substitute for enforcement at execution boundaries.

The active wall-time window is itself an invariant: `resume` may start a fresh window only when the session has genuinely gone idle. Resuming a workflow that is still being actively driven must preserve the consumed budget, so repeated resumes inside one wall-budget horizon cannot extend the window. A legitimate fresh window never resets durable attempt/send-back/recovery/revision counters.

### 5.7 Verification pyramid

#### L0 — unit / schema / policy / invariant

Purpose: pure deterministic behavior.

Examples:

- asset-workspace identity matching;
- mutation/authority contracts;
- geometry infeasibility math;
- budget/watchdog state transitions;
- canonical preflight policy functions.

Expected order of magnitude: seconds.

#### L1 — fixture / CLI / workflow integration

Purpose: reproduce real failed-workflow conditions without full media production.

Requirements:

- #138 F1–F4 each have a deterministic regression at L0 or L1;
- probe/preflight parity is exercised through supported interfaces;
- no full 60-second production render;
- no network search/download dependency for the core regression.

Target: the stabilization regression set should remain comfortably CI-scale; an initial target of <=120 seconds for the dedicated L1 set is a performance target, not a replacement for correctness.

#### L2 — targeted Chromium / ffmpeg / media smoke

Purpose: verify behavior that genuinely depends on real browser/media execution.

L2 must operate on the smallest relevant slice: the failing moment/shot/window or a lightweight representative fixture, not the full production video.

Independent L2 checks should run in parallel when practical. CI should retain useful evidence such as structured diagnostics, screenshots/stills, render metadata, or ffmpeg/Chromium logs when those artifacts make failure diagnosis faster.

#### L3 — fresh cold production shadow

Purpose: end-to-end production acceptance.

L3 is not the normal debugging loop. It may start only after the Stabilization Gate is green on an exact merged `main` SHA.

P4 timing/telemetry acceptance remains owned by #107, including the existing cold-cache timing and causal-coverage targets.

If L3 discovers a new engineering failure, that failure must first be reduced to an L0/L1 fixture, or an L2 targeted smoke when irreducibly environment-dependent, before another L3 rerun is authorized.

## 6. Stabilization Gate

A fresh cold P4 shadow is authorized only when all of the following are true on merged `main`:

1. F1 hard-region infeasibility has a fast regression and provably impossible geometry is rejected before browser/candidate consumption.
2. F2 has a read-only/context-equivalent probe whose blocking result matches official preflight for the same input and authority context.
3. F3 rejects an edit identity absent from durable asset-workspace review before candidate consumption, and promotion enforces manifest/edit identity equality.
4. F4 stops a simulated in-phase overrun on the next execution boundary/front-door command and persists actionable budget evidence.
5. The failed-shadow cases required for F1–F4 are represented by deterministic fixtures or explicitly justified L2 fixtures.
6. The targeted Chromium/ffmpeg smoke relevant to these changes is green.
7. Required GitHub CI is green.
8. No known stabilization blocker is being deferred merely to “see what the full render does.”

Passing this gate authorizes exactly the next fresh acceptance attempt; it does not make future engineering failures exempt from the fixture-first rule.

## 7. Workstreams and dependency order

Implementation must be split into reviewable PRs. Independent verification should run in parallel where safe.

### Wave 1 — make failure cheap and bounded

#### A. In-phase watchdog (maps to F4)

Establish the guardrail first so subsequent development cannot silently repeat multi-hour in-phase execution.

Deliverables:

- execution-boundary budget enforcement;
- stable persisted timeout state/evidence;
- regression for simulated in-phase overrun.

#### B. Failed-shadow fixture harness

Build the minimal fixture format/helpers required to represent the #138 failure evidence without running the full project.

A and B may proceed in parallel if their code surfaces do not conflict.

### Wave 2 — remove divergent authority paths

#### C. Canonical preflight + read-only probe (maps to F2)

Refactor or route both official preflight and diagnostic probe through one canonical policy implementation and authority loader.

#### D. Workspace-bound asset/edit operation (maps to F3)

Replace field-level trust with durable reviewed candidate identity. Refuse unreviewed windows and enforce promotion equality.

#### E. Geometric fail-fast (maps to F1)

Add the provable-infeasibility pre-check ahead of Chromium and candidate consumption.

C, D, and E may be implemented in separate PRs and verified in parallel after Wave 1 provides the fixture/budget foundation.

### Wave 3 — targeted media verification

#### F. L2 targeted smoke + CI evidence

Provide the smallest Chromium/ffmpeg smoke necessary for the affected paths, with useful failure artifacts. Make CI change-aware where practical without reducing required safety coverage.

### Wave 4 — one fresh cold acceptance

#### G. Fresh P4 shadow

After A–F are merged, required CI is green, and the Stabilization Gate is satisfied:

1. identify the exact merged `main` SHA;
2. sync that exact SHA to Mac;
3. start a fresh cold P4 shadow project;
4. run production acceptance to `awaiting_human` or a real bounded blocker;
5. collect timing, causal telemetry, diagnostics, and render evidence required by #107.

Do not reuse the failed shadow project as the acceptance run.

## 8. Required regression matrix

| Failure / invariant | Earliest required layer | Required assertion |
| --- | --- | --- |
| F1 hard-region infeasibility | L0/L1 | provably impossible placement is rejected before browser and before candidate count changes |
| F2 probe divergence | L1 | same canonical draft + authority context => same blocking set for probe and official preflight |
| F3 unreviewed source-window reuse | L0/L1 | absent exact reviewed asset identity is refused at edit-stage before candidate consumption |
| F3 promotion mismatch | L0/L1 | manifest identity != edit-shot identity cannot promote |
| F4 in-phase wall overrun | L0/L1 | next execution boundary persists `needs_decision` / `wall_budget_exceeded` and starts no new expensive work |
| Browser/media-dependent placement path | L2 | targeted slice exercises real Chromium path with evidence; no full video required |
| Production convergence | L3 | fresh cold exact-SHA run satisfies #107 acceptance or stops at a real bounded blocker |

## 9. CI and evidence contract

GitHub remains the primary verification engine.

- L0/L1 run in CI for relevant changes.
- L2 runs when touched paths can affect browser/media behavior; change-aware selection is allowed only when required safety coverage is preserved.
- Independent jobs should be parallelized where practical.
- Failure output should identify the layer, canonical fixture, diagnostic code, and authoritative context used.
- Browser/ffmpeg failures should retain useful lightweight evidence when practical.
- A green unit suite alone is not permission to skip a required L2 check.
- A green L0–L2 stack is necessary but not sufficient for final production acceptance; L3 remains required by #107.

## 10. Tracking policy during stabilization

#107 remains the P4 acceptance umbrella.

#138 remains the stabilization/failure-evidence tracker for the four known classes F1–F4 and same-class symptoms discovered while implementing this spec.

During stabilization, a new symptom that is an instance of F1–F4 should be recorded as evidence/regression under #138 rather than creating another issue.

A new issue is justified only when the finding is a genuinely separate architectural concern or independently schedulable scope that cannot be represented truthfully under #138. Issue creation must not be used as a substitute for reducing a failure to a regression fixture.

Implementation PRs should reference both this document and the relevant tracking issue(s).

## 11. Preservation and migration rules

- `p4-shadow-first-date-first-text-2cc3664-20260925-000753` stays failed-shadow evidence.
- Its workflow state, historical telemetry, candidate history, and review evidence are not retroactively rewritten to satisfy the new architecture.
- New fixture material may be derived from its recorded evidence, but derivation must not mutate the source project.
- No current-project acceptance is inferred from a fixture passing.
- The next production acceptance project is fresh and starts from the exact merged SHA after the Stabilization Gate.

## 12. Exit criteria

This stabilization spec is complete when:

1. Waves A–F are merged through normal GitHub PR/CI/review flow.
2. F1–F4 are protected by the regression matrix above.
3. The Stabilization Gate is green on an exact merged `main` SHA.
4. One fresh cold P4 L3 run is executed from that SHA.
5. The L3 run reaches valid `awaiting_human` acceptance under #107, or produces a new bounded blocker that is reduced to the appropriate lower verification layer before any rerun.

If the fresh L3 run exposes a new blocker, this spec is not considered a failure. The required behavior is that the blocker becomes cheap and deterministic to reproduce before another expensive acceptance attempt.

## 13. Workflow contract

All implementation remains subject to the project workflow:

`GitHub branch -> implementation -> tests/CI -> PR -> review -> merge -> exact merged SHA -> Mac execution/acceptance when environment-dependent`

`main` is never edited directly. GitHub is the source of record. Mac findings produce evidence; final fixes return through GitHub.
