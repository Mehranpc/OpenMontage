# Persian footage review policy

This file is the single review-exhaustion rule for the Persian production path.

## Authority

- The active pipeline manifest owns the revision ceiling at `orchestration.max_revisions_per_stage`.
- The run pins `orchestration.policy_version` and `orchestration.active_profile` at start.
- `lib/checkpoint.py` remains the only authority for progress and human approval.

## Decision

1. With no critical findings, continue. Suggestions and nitpicks are recorded but do not block.
2. With critical findings and remaining revision budget, revise and review again.
3. With critical findings after the manifest ceiling is exhausted, stop automation.
4. Record checkpoint `status=failed` and `metadata.quality_disposition=needs_decision` with the unresolved blockers.
5. Never describe that result as final or deliverable. A user may explicitly request a clearly labelled draft.

## Profile routing

For `film-type-2.16`, load only the current Film Type contract and current phase card. Legacy Film Type history is diagnostic reference and must not be mixed into `review_focus` or execution instructions.
