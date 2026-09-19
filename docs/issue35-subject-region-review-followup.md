# Issue #35 — Subject-region review follow-up

The bounded recovery contract now has a dedicated `SUBJECT_REGION_REVIEW` class and a fail-closed subject-region evidence validator. This deliberately avoids misclassifying missing reviewed regions as typography/layout recovery.

One architectural follow-up remains: `complete_phase(..., phase="review_subject_regions")` does not yet invoke `validate_subject_region_review_evidence()` directly. Current production acceptance must therefore run the canonical validator before completing that phase. This is explicit debt, not permission to bypass the validator or to treat unvalidated evidence as durable phase truth.

Future wiring should call the validator at the front-door completion seam and persist only normalized evidence, without moving the invariant into telemetry or renderer code.
