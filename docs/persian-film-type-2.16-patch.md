# Persian Film Type 2.16 patch

Issue #32 advances the active Persian Film Type profile from 2.15.0/layout 15 to 2.16.0/layout 16.

The new profile declares a dedicated editorial display contract for opening hooks and semantic body callouts: `KahrobaEditorial`, sourced from the licensed `Kahroba BL-LC` face, white support ink, semantic yellow `#FFEA00`, right/center Persian alignment, complete multi-line hooks up to five measured lines, and no truncation.

The font binary is a private licensed runtime asset and is not redistributed by this repository. Runtime installation copies the licensed source into the fixed Remotion asset path and verifies SHA-256 `0223838295d7fb72a6dce709d234ef433d7815f66ed83b6959ae2f838f3d6711`. Historical 2.15 behavior is frozen in `styles/persian-footage/film-type-2.15.0.json`.

2.16 initially inherits all 2.15 watermark, mastering, safe-area, adaptive pixel measurement, and deterministic convergence protections. Issue #32 adds the new editorial paint/QA behavior without weakening those protections.
