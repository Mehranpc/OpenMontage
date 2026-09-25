# P4 failed-shadow fixtures

`issue138-v1.json` is immutable test evidence derived read-only from failed shadow
`p4-shadow-first-date-first-text-2cc3664-20260925-000753` and GitHub Issue #138.

The fixture intentionally contains only authority needed to reproduce F1-F4. It
contains no machine-local absolute paths and no production media dependency. When
the failed evidence did not define a future contract value (for example the new F3
diagnostic code or the unreviewed edit's crop identity), that absence is recorded
explicitly rather than inferred.

Do not rewrite an existing version to make a new implementation pass. If source
evidence or the fixture schema legitimately changes, add a new version and retain
the historical fixture.
