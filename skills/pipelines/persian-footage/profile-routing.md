# Persian footage profile routing

Read this table before loading any profile-specific instruction.

| Resolved profile | Load | Do not load |
| --- | --- | --- |
| `film-type-2.16` (default) | `film-type.md`, the current phase card, and the current stage director only when the card links to details | `film-type-history.md`, Legacy geometry/review recipes, old patch notes |
| Pinned Film Type `<2.16` | `film-type.md` pinning rules, the exact version patch note, and only the matching historical section | unrelated versions and Legacy verifier rules |
| Explicit emergency `legacy` | the Legacy renderer/verifier contract named by the project pin | Film Type geometry as if it certified Legacy output |

## Rules

- The run pins `orchestration.policy_version` and `orchestration.active_profile` at bootstrap.
- New unpinned production always resolves to `film-type-2.16`.
- `film-type-history.md` is diagnostic input, never eager context.
- A phase loads one short card first. It opens a director/reference only for details named by that card.
- Conflicting rules stop as `quality_disposition=needs_decision`; never blend profiles.
