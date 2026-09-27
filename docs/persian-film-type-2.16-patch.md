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

## Watermark relocates beside text (#215)

The brand yields to editorial text by moving, not by disappearing:

- While a moment is on screen, the brand stays out of that text's whole vertical band.
  Text at upper-right sends the brand to a lower anchor, not to upper-left beside it,
  and the brand keeps `minTextClearancePx` from the text.
- A burned caption blocks the brand only while it actually paints. Captions hide
  whenever a moment owns the frame, so they no longer close the lower anchors under
  every moment.
- With burned captions active, the lower anchors sit above the caption band by the
  same clearance, so a painting caption does not evict the brand from the lower band.

Coverage stays governed by `minCoverageRatio` (0.70; the intended range is 60-70% of
runtime) and the brand may still be briefly absent where no anchor is clear. In a
62.5s hybrid-caption run with seven upper moments, coverage went from 36% (a hard
`WATERMARK_COVERAGE` stop) to 92%. The profile tokens are unchanged, so the pinned
2.16 hash is unchanged. Older pins plan exactly as before.

## Faces, brand distance and presence, «یا» phrases (#230)

- Subject-region review must mark the face (`face` grid rect, merged as hard) in every non-clear
  frame of a shot whose asset has `human_presence: true`, or state `face_visible: false`.
  Placement avoids hard regions only; an unmarked face is where the hook landed.
- Brand presence is 55-75% of runtime (was a 70% floor that planned 92%). Coverage beyond 75%
  no longer scores; the planner leaves gaps, preferably while text is up. Applied in code, so
  the pinned 2.16 token hash is unchanged.
- The brand prefers the anchor farthest from live text, never stacks under a moment block
  (centre within the block's column) without a 5x-clearance gap when coverage allows, and sits
  2x clearance above the burned-caption strip.
- «یا»-joined three-way choices lock each 2-4 word option like comma lists, so
  «فردا صبح» never breaks across rows.

