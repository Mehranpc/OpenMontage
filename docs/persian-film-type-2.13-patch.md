# Persian Film Type 2.13 patch

Film Type 2.13.0 / layout 13 is the current default for unpinned
`persian-footage` runs. Film Type 2.12.0 remains pinned and reproducible at
`styles/persian-footage/film-type-2.12.0.json`.

## Coverage-aware watermark planning

The first 5 seconds remain clean. After that delay, 2.13 plans safe watermark
slots across shot, moment, caption, and supplied subject-region boundaries.
Unsafe intervals may remain blank; they are not repaired by trimming a chosen
slot or by weakening supplied geometry.

For videos at least 20 seconds long, measured watermark coverage must be at
least 70% of total duration and targets 80%. Coverage below 70% is a refusal;
70% through 80% is an advisory. For videos under 20 seconds, the floor is
bounded by the time actually available after the clean intro. If that remaining
window is shorter than the normal 6-second dwell, the single short-form dwell
may use the whole available window; normal and long-form dwells remain at least
6 seconds.

Long-form relocation is a target rather than a safety override. The planner
prefers at least two relocations and multiple safe zones when geometry permits,
but safe measured coverage remains authoritative.
## Caption geometry

Film Type 2.13 centers the burned-caption band physically in the frame by using
the larger horizontal safe-side inset on both sides. A pinned 2.12 render keeps
its historical asymmetric geometry.

## Validation and approval

Coverage and relocation warnings are machine evidence, not human approval.
Preparation still refuses stale geometry, unsafe overlaps, and measured coverage
below the applicable floor. Final candidates remain subject to render QA and
must stop at `awaiting_human`; automation must not set human approval to true.
