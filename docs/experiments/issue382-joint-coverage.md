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
