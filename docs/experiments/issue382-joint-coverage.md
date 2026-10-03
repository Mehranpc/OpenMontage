# #382 increment B — joint-coverage experiment (pre-registration)

Status: **harness only; no result recorded yet.** This document is written before any
real corpus is evaluated. It is not a budget grant, a sourcing policy or evidence that
stock supply is solved.

## Hypothesis under test (H2)

Independently admissible reviewed alternates for different unresolved events can
conflict with one another through visible source-window overlap (same provider and
source, overlapping window). Walking events one at a time may then cover fewer events
than a jointly compatible choice.

H1 (local-window-first) is **deferred**: the digest-bound frontier carries no source
duration and a new window needs fresh frame evidence plus normal admission, so it
cannot be measured honestly from frozen records alone.

## Harness

- `lib/persian_recovery_experiment.py` — pure functions over a frozen
  `preparation.recoveryEvidence` report. No workspace, provider, browser, media,
  selection or write access.
- `scripts/recovery_joint_coverage.py <status-or-report.json>` — prints the sanitized
  corpus and its certificate. Read-only.

Sanitized corpus keeps: event id, candidate status, admission codes, rejection
category, hashed source identity and source window. It drops candidate/provider ids,
rejection reason text, review digests, crops and every path. Rows whose identity
cannot be projected become `unavailable` and make the corpus incomplete.

## Metrics (fixed before results)

| Metric | Meaning |
| --- | --- |
| `independentCoverage` | events with at least one admissible row |
| `sequentialCoverage` | baseline: events in order, first compatible row in ref order |
| `maxJointCoverage` | exact bounded maximum of simultaneously compatible events |
| `jointGainOverSequential` | `maxJointCoverage - sequentialCoverage` |
| `eventsWithoutKnownAdmissible` | events the frontier cannot help (still need a decision) |
| `decideTogether` / `conflicts` | event groups whose choices interact |

Statuses: `jointly_compatible`, `conflicted`, `no_known_admissible`, `unknown`
(incomplete evidence or exhausted search budget). The certificate never contains an
assignment; selection remains `asset-candidate-select` with shared admission.

## Decision rule

1. Corpus: the real exhausted production frontier, exported at an exact green main
   SHA, sanitized by this harness and published before interpretation.
2. Adopt joint-compatibility guidance in workflow status (separate PR) only if the
   real corpus shows `jointGainOverSequential > 0` or non-empty `conflicts`.
3. If the real frontier shows `no_known_admissible` or zero gain, H2 is **rejected for
   this corpus**, the correct outcome stays `needs_decision`, and nothing ships.
4. `unknown` is not a pass: repair evidence first, never guess.

## Negative controls (CI)

Absence of admissible rows, incomplete evidence, unprojectable identities and an
exhausted search budget must never yield success or proof of impossibility. Distinct
windows of the same source never conflict (no global source blacklist). Synthetic test
rows check harness mechanics only and are not decision evidence.

## Result 1 — real exhausted frontier (recorded after harness merge)

- Code: exact main `d0b51e00ca1b30baa0fac1c9c5222f240cd45fdd` (both official CI jobs green),
  checked out detached on the production Mac; run `persian-p0-first-date-20261002`.
- Commands: `python -m lib.persian_video_workflow status <run> --json`, then
  `scripts/recovery_joint_coverage.py`. Project state was unchanged except the CLI's own
  append to `.telemetry/command-events.jsonl`.
- Report `inputsSha256` `dd955322a8a1c68eed9afff9d77327a4d0c83e20da2fc6c21c58fd646abbf8dc`;
  corpus `8991aeb7b8fba7c62640eff842e255668e43523020409da7207b7be0a23cd0be`
  (published in `issue382-corpus-p0-first-date.json`), evidence complete.

| Event | Known candidates | Status | Rejection categories |
| --- | --- | --- | --- |
| ev-01 | 6 | all rejected | semantic 4, technical 2 |
| ev-02 | 6 | all rejected | semantic 3, editorial 2, technical 1 |
| ev-03 | 5 | all rejected | semantic 4, technical 1 |
| ev-04 | 5 | all rejected | semantic 3, editorial 1, technical 1 |
| ev-11 | 5 | all rejected | semantic 4, editorial 1 |

Certificate: `no_known_admissible`; independent, sequential and joint coverage all 0;
no conflicts.

**Decision (per rule 3): H2 is rejected for this corpus.** Joint-compatibility guidance
does not ship. The run correctly stays `needs_decision`.

### Observation that motivates H1 (not a result)

Read-only aggregate over the same run's candidate records (counts only):

- 46 of 47 staged candidates in the run use source window start `0.0` — the
  `source_in_seconds` default when a staging payload omits it.
- For the 27 rejected identities of the 5 missing events, every source duration is
  known; unexplored seconds after the reviewed window: min 2.94, median 10.69, max 89.68.
- 25 of 27 have room for at least one further non-overlapping window of the same length
  (semantic 18, technical 4, editorial 3).

This shows unexamined window space in already-downloaded clips; it does **not** show
that any later window is semantically suitable. A semantic rejection may describe the
whole clip. H1 needs its own pre-registered test with fresh frame evidence and normal
admission before any change in guidance or defaults.
