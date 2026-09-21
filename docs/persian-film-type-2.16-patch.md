# Persian Film Type 2.16 patch

Issue #32 advances the active Persian Film Type profile from 2.15.0/layout 15 to 2.16.0/layout 16. Historical 2.15 behavior is frozen in `styles/persian-footage/film-type-2.15.0.json`; do not rewrite old pins.

## Hook authority

A hook supplied at production bootstrap is authoritative. Without a user hook, automatic selection uses the repository-owned Persian Hook corpus, compares multiple candidates, rejects unsupported claims before ranking, requires content-match 2/2, and persists the winner. Edit staging is bound to that durable decision; visual segmentation may change but the words/punctuation may not be silently rewritten.

## Editorial visual system

Every video opens with one complete 3–5 second Hook Typography composition. The registered display family is `KahrobaEditorial`, sourced from the licensed `Kahroba EB-LC` face. Supporting text is `#FFFFFF`; semantic emphasis is `#FFEA00`. Persian editorial alignment/placement is right or center, never left. Hooks may use up to five measured lines and are not truncated. The active recipes deliberately permit stronger poster-like occupancy than 2.15 so complete copy is not shrunk into timid overlay text.

The same visual language is available to semantic body callouts and enumerations. Burned captions suppress themselves while an editorial moment owns the frame and resume afterward. Callouts may paraphrase the current narration unit but must preserve its meaning.

## Font asset boundary

The Kahroba binary is a private licensed runtime asset and is not redistributed by GitHub. Install a licensed source with `python scripts/install_kahroba_font.py "/path/to/Kahroba EB-LC.woff2"`. The expected SHA-256 is `354d3f6fd8f3a330a766d403beac0a37d3d7378a754067265d766ee1a1cae14d`. The installer verifies bytes before/after copy and the browser verifies the same digest before measurement/paint. Missing or mismatched bytes fail closed.

## Timing and rendered QA

The opening hook is simultaneous: no Stop/Lock card sequence and no delayed child segment. On 2.16, the opening product contract is 3–5 seconds; the older character-count/CPS timing proxy does not get to mutilate a complete hook. Real Kahroba pixel measurement plus rendered visual review are authoritative.

Rendered Visual Typography policy v2 requires a Kahroba display family, complete hook visibility, right/center alignment, actual white/yellow semantic hierarchy, non-subtitle-like treatment, local contrast, hierarchy, line balance, optical placement, and measured occupancy/duration evidence. Mute-safe cold-viewer evidence remains required.

## Non-destructive convergence

Preflight revisions may adjust recipe, line plan, placement, timing, or presentation, but may not silently delete semantic editorial moments. Intentional removal requires an explicit user response with the exact removed IDs, reason, and decision provenance.

## Placement and watermark

Reviewed subject regions are authoritative typography-placement evidence in 2.16: hooks and body callouts must move away from, or refuse, a measured placement that intersects a reviewed face/body/action region. Platform safe area remains hard. Watermark planning stays the deterministic 2.15 text-only fixed-anchor system and receives no subject/face/body blockers.

## Honest production timing

`workflow_wall_seconds` measures real end-to-end wall time. Instrumented editorial work, provider/external time, review-phase time, and unattributed/orchestration gaps remain separate dimensions. The 30/45-minute production goal is an SLO/architecture signal, not a correctness kill switch.

## Preserved protections

2.16 retains Issue #28 opening-first rendering, digest-bound promotion, canonical mastering before final SHA identity, deterministic watermark coverage, caption authority, safe areas, provenance, final review, and the terminal `awaiting_human` checkpoint.
