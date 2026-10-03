# Asset acquisition reference

Open only for active acquisition, candidate review, alignment, or music details.

## Provider request

First pass contains one primary query per footage event and one candidate each. Retry once only for unresolved events, using authored alternate queries in `audit_scene_plan(...)["sourcing_order"]`. Pexels honours orientation; every download is still ffprobed and mismatches are deleted. Pin both min/max width to 1080 for portrait delivery.

## Candidate identity and evidence

Identity includes provider/source ID, exact source-time window, and intended crop. Changing window or crop creates a new identity and needs new review. Review start/middle/end of the selected crop for subject/human continuity, affect, semantics, crop/text safety, motion, staged-stock risk, and resolution. Preserve technical, semantic, and editorial rejection categories separately.

Selection may reuse unchanged reviewed alternates after send-back. It rejects overlapping windows from the same source but permits distinct non-overlapping windows. Copy the workflow's manifest binding/evidence exactly; canonical selected output remains `asset_manifest`.

## Manifest essentials

Each row carries event lineage, narration span, query/rank, video kind/path, source window, dimensions, provider/source/original URL, licence/attribution, crop, durable candidate/review hashes, subject/human/affect evidence, risk, fallback reason, selection/relevance reason, and frame review. The real path is authoritative; do not pre-stage under Remotion public.

## Alignment

The provider seam is durable and policy-owned. Use `alignment-plan/start/status/commit`, language `fa`, and approved-script alignment. Provider text never becomes delivered Persian copy.

## Music

Pixabay music is the approved provider and the default; do not ask the user unless their request named or supplied a track. Select instrumental audio at least as long as delivery. Persist path, source, licence name/URL/download date, attribution, and Content-ID risk. Narrated mode requires music or explicit deliberate silence. Unknown risk needs acknowledgement; high risk is refused.

## Selection admission (#360)

`asset-candidate-select` checks the candidate against its planned visual event in the effective scene plan with the manifest audit's own rules, before anything is written. A refusal lists every blocker it can already prove at once — stable `code`, `field`, planned `expected`, reviewed `observed`, `recovery` categories — as JSON on stdout (`{"refused": true, "diagnostics": [...]}`) and as `[CODE] message` text; the ledger, dispositions and reviews stay unchanged. Replacement and re-selecting the current pick are admitted by the same rules. No plan, an unreadable plan, or an event missing from the plan refuses (`PLAN_MISSING`, `PLAN_INVALID`, `EVENT_NOT_IN_PLAN`).

| Rule class | Checked | Rules |
| --- | --- | --- |
| `event_local` | at selection | provenance, allowlist, path; usable duration; beat/span/query/rank; reasoning; affect; staged risk; human presence; subject continuity; reviewed fallback; start/middle/end frames; opening-hook frames; carrier `placement_space`; crop safety |
| `current_set` | at selection | overlapping source window with another selected event |
| `manifest_declaration` | returned as `declarationsRequired`, audited at build | fallback or opening semantic fields the review did not record |
| `completion` | build-manifest / checkpoint | every planned event has exactly one row; typographic beats carry no footage |

Record the treatment you actually see in the review when it is not the literal one: `"fallback_level": "adjacent_metaphor", "fallback_reason": "..."` (a reason is required for every non-literal level). Admission then compares it with the planned level, and the manifest carries it; a build override cannot contradict it. Without it, the row defaults to `exact_literal` and a non-literal plan returns a `FALLBACK_UNDECLARED` declaration you must make at build or `reconcile-plan` with evidence. `human_presence` is never reconciled away to fit a clip: pick a reviewed alternate or reject and retry.

`status` checks the recorded selections against the current plan with the same rules, and it is read-only: it does not materialise the plan, spend a pass or write anything. `acquisition.recordedSelectionCount` is how many events have a selection. `validSelectionCount` is how many of those still pass. `invalidEvents` and `staleEvents` name the rest, and `readiness.diagnostics` gives the reasons. `unresolvedEvents` still means events with no selection. `readiness.inputsSha256` changes when the plan, a selection, a review or the policy changes. Build the manifest only when `readiness.disposition` is `ready_for_manifest` (or `..._with_declarations`, after making the named declarations). If an existing selection no longer passes, you can reject it directly with `asset-candidate-reject`. That releases the selection, records the admission codes, and puts the event back into `unresolvedEvents` for the normal retry route. A selection that still passes must be replaced, as before.

When the review records `opening_semantic_match`, `semantic_role` or `semantic_direction`, admission checks that recorded evidence immediately. The manifest preserves it, and build overrides cannot contradict it. Only absent fields remain manifest declarations; a recorded negative opening match must be repaired by choosing suitable footage.

Readiness binds both the selection ledger's expected hashes and hashes recomputed from the candidate's actual identity, context and immutable review. A torn record is reported as `CANDIDATE_EVIDENCE_STALE`, excluded from valid coverage, and changes `inputsSha256`; inspecting it never rewrites its evidence. Admission uses the same integrity check: reselecting stale evidence, including an idempotent pick, refuses before any write even without an expected-readiness argument.

A completed scene-plan checkpoint remains authoritative when damaged: malformed checkpoint/artifact mappings and absent or empty beat requirements produce `PLAN_INVALID`, never a clean readiness or fallback to an older plan artifact. Valid artifact-only legacy plans remain readable, and diagnosis does not materialise or rewrite either source.


## Scoped recovery before edit (#377)

For a current region proposal with protected-subject collisions or an unplaceable opening hook, use `send-back <project-id> acquire_assets --code ASSET_SELECTION_HARD_REGION_COLLISION --shot-id <affected-id> [...] --reason "<actual finding>"`. The front door validates current scene/manifest dependencies and sheet/frame digests, recomputes findings from reviewed proposal regions, and admits only affected shots. It derives a recovery-only shot/event view and writes no edit artifact. Existing-option priority, scoped asset/music guards, and send-back ceilings still apply. Stale evidence requires refreshed sheets/proposal; do not fabricate edit decisions to authorize this earlier-phase repair.

## Evidence frontier at exhaustion (#382)

When no search pass or send-back remains and no pass is pending, `status.acquisition.preparation.recoveryEvidence` projects the known candidate evidence for blocked/missing events. `admissible` means the existing admission rules allow that reviewed alternate against the current plan and selected set; `blocked` lists admission codes. `rejected` preserves the recorded exact-identity reason, `unreviewed` grants nothing, and `unavailable`/`unreadableRecordIds` make diagnosis incomplete (`complete: false`). `complete: true` describes the known-record scan, never proof that stock cannot satisfy the brief. This is not a browser-fit, region-review or rendered-quality approval.

Prepare the next explicit decision from these facts, not by repeating a rejected source/window or treating downloads as accepted footage. A different source window/crop is a different identity and still needs actual review; there is no global source blacklist. The report is read-only, also at a persisted budget stop; it grants no pass/time and performs no provider/browser work. `recoveryEvidence.inputsSha256` binds the report and candidate bytes separately; it is **not** an `--expect-readiness` token. Use `readiness.inputsSha256` for the existing mutation contract. All authority, counters and approval gates remain unchanged.

`recoveryEvidence.localWindowCapacity` lists, per blocked/missing event, each exact source already known for that event: its duration, every known window of that source from any event or status, `openingWindowOnly`, the `unexploredSpans`/`unexploredSeconds` no record has examined, and `distinctWindowsFitting` (non-overlapping windows of the event's longest known window length). On the first real exhausted run 46/47 candidates used the opening window only (#382). Unexplored time is **not** evidence that footage fits: a semantic rejection may describe the whole clip. A later window is a new identity; stage it with an explicit `source_in_seconds`, review its actual frames and pass normal admission. Unknown or conflicting duration stays `null`. When allowances are spent, whether to examine such windows is an explicit decision; this report grants no pass, time or send-back.

`asset-candidate-stage` returns `sourceWindowDeclared`; when it is `false` the payload omitted `source_in_seconds` and the opening window (0.0s) was staged, with `sourceWindowWarning`. Declare the reviewed window explicitly.
