# Persian Film Type 2.15 patch

Film Type 2.15.0 / layout 15 is the current default for unpinned
`persian-footage` runs. Film Type 2.14.0 is frozen at
`styles/persian-footage/film-type-2.14.0.json` and remains pinnable.

## Adaptive editorial typography

2.15 replaces the pre-render character-count refusal on the adaptive Film Type
path with browser-measured pixel fitting. Copy length alone is not a render
failure. The loaded Estedad font, safe area, measured line breaks, stack height,
and selected editorial recipe determine whether a candidate is legal.

Agents cannot emit arbitrary CSS or free-form font sizes. They may select only
curated `recipeId` values registered in the Film Type profile. The initial set is
`editorial-hero-balanced`, `editorial-hero-compact`, and
`editorial-callout-balanced`.

Each recipe constrains column fractions and hero/support line counts. The upper
occupancy bound is a hard fit limit; the target and lower occupancy preference
rank otherwise legal candidates instead of deleting copy. The browser still
searches the versioned type-size ladder and rejects the moment if no measured
candidate fits. Existing 2.14 and older pins
retain their historical character-limit and layout behavior.

## Fixed-anchor watermark planning

2.15 removes shot subject/face geometry from watermark planning. The watermark
planner receives no `avoidRegions` for this profile. Its authoritative blockers
are the platform safe area plus the measured rectangles of editorial text and,
when active, burned captions.

The brand moves only among the approved corner anchors: upper-left, upper-right,
lower-left, and lower-right. Coverage, dwell, intro delay, and measured
brand-to-text clearance remain enforced. A face scan or image-composition result
cannot suppress, relocate, or rescue the watermark in 2.15.

This separation is deliberate: typography review may still use reviewed subject
regions for its own placement contract, while watermark safety is deterministic
from text geometry and fixed anchors alone.

## Validation and approval

2.15 is a new profile rather than an in-place edit of 2.14. Its canonical hash is
pinned by Python and browser preparation. Saved 2.14 snapshots keep their exact
historical renderer contract.

Opening-gate review and final audio mastering remain part of the front-door
workflow. Final candidates still stop at `awaiting_human`; machine-readable
preflight and rendered review evidence do not constitute human approval.
