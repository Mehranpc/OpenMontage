# Persian Film Type 2.14 patch

Film Type 2.14.0 / layout 14 is the current default for unpinned
`persian-footage` runs. Film Type 2.13.0 is frozen at
`styles/persian-footage/film-type-2.13.0.json` and remains pinnable.

## Opening hook legibility

2.14 keeps the clause-level opening contract and permits the authored phrase to
use the normal role hierarchy instead of deleting grammar to save width. A hook
may therefore carry a small `lead` above a prominent `hero` and a supporting
`tail`, e.g. `برای` / `هر کار خوبی` / `جایزه می‌دی؟`.

Bright opening footage gets a stronger bounded dark field and stronger glyph
separation than 2.13. This is still a readability aid rather than a contrast
measurement; frame review remains required.

## Burned-caption refinement

The 2.14 burned-caption treatment is slightly smaller and lighter in weight,
with a softer dark field and shadow. Physical centering from 2.13 is retained.
The browser remains the authoritative pixel-fit check; type is not shrunk to
force an over-wide cue.

Burned grouping also repairs a stranded discourse opener when it can join its
following clause within the same approved-script timing and display budgets.
This prevents fragments such as `از طرفی، بچه` from appearing as a complete
caption block while preserving exact narration wording.

A burned cue that starts under an editorial moment and would leave less than one
second visible after that moment exits is suppressed completely. This removes
brief post-moment caption flashes; the hybrid/sidecar SRT still retains the
approved words.

## Watermark anti-crop diversity

The first five seconds remain clean. The 70% hard coverage floor and 80% target
from 2.13 remain unchanged, as do measured text/subject clearances and the normal
six-second dwell.

For long-form video, 2.14 additionally prefers schedules spanning at least two
vertical bands (upper/mid/lower) when safe geometry permits, alongside the
existing relocation target. Normal dwells remain at least six seconds. A single
diversity-only dwell may use a shorter reviewed-safe window down to four seconds
when that slot introduces a new vertical band; this exception cannot create the
first slot or weaken subject/text clearance. Coverage and collision safety remain
authoritative: the planner does not park a watermark on a reviewed subject merely
to satisfy a diversity preference.

## Audio review remains mix-level evidence

Film Type does not prescribe one music gain for every source track. Final review
must measure and listen to the actual narration/music combination: clipping is a
hard defect, while a bed that is technically present but perceptually absent is
an editorial mix defect. Adjust render inputs, not the canonical narration.

## Validation and approval

2.14 is a new profile rather than an in-place edit of 2.13. Its canonical hash
is pinned by both Python and browser preparation. Existing 2.13 snapshots keep
their historical caption style, contrast, and watermark planning.

All final candidates still stop at `awaiting_human`. Render QA, transcript
comparison, luminance/motion checks, and machine-readable preflight evidence do
not constitute human approval.