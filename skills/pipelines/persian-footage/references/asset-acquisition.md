# Asset acquisition reference

Open only for active acquisition, candidate review, alignment, or music details.

## Provider request

First pass contains one primary query per footage event and one candidate each. Retry once only for unresolved events, using authored alternate queries in `audit_scene_plan(...)["sourcing_order"]`. Pexels honours orientation; every download is still ffprobed and mismatches are deleted. Pin both min/max width to 1080 for portrait delivery.

## Candidate identity and evidence

Identity includes provider/source ID, exact source-time window, and intended crop. Changing window or crop creates a new identity and needs new review. Review start/middle/end of the selected crop for subject/human continuity, affect, semantics, crop/text safety, motion, staged-stock risk, and resolution. Preserve technical, semantic, and editorial rejection categories separately.

Selection may reuse unchanged reviewed alternates after send-back. It rejects overlapping windows from the same source but permits distinct non-overlapping windows. Copy the workflow's manifest binding/evidence exactly; canonical selected output remains `asset_manifest`.

## Manifest essentials

Each row carries event lineage, narration span, query/rank, video kind/path, source window, dimensions, provider/source/original URL, licence/attribution, crop, durable candidate/review hashes, subject/human/affect evidence, risk, fallback reason, selection/relevance reason, and frame review. The real path is authoritative; do not pre-stage under Remotion public.

## Alignment

The provider seam is durable and policy-owned. Use `alignment-plan/start/status/commit`, language `fa`, and approved-script alignment. Provider text never becomes delivered Persian copy.

## Music

Pixabay music is the approved provider and the default; do not ask the user unless their request named or supplied a track. Select instrumental audio at least as long as delivery. Persist path, source, licence name/URL/download date, attribution, and Content-ID risk. Narrated mode requires music or explicit deliberate silence. Unknown risk needs acknowledgement; high risk is refused.

## Selection admission (#360)

`asset-candidate-select` checks the candidate against its planned visual event in the effective scene plan with the manifest audit's own rules, before anything is written. A refusal lists every blocker it can already prove at once — stable `code`, `field`, planned `expected`, reviewed `observed`, `recovery` categories — as JSON on stdout (`{"refused": true, "diagnostics": [...]}`) and as `[CODE] message` text; the ledger, dispositions and reviews stay unchanged. Replacement and re-selecting the current pick are admitted by the same rules. No plan, an unreadable plan, or an event missing from the plan refuses (`PLAN_MISSING`, `PLAN_INVALID`, `EVENT_NOT_IN_PLAN`).

| Rule class | Checked | Rules |
| --- | --- | --- |
| `event_local` | at selection | provenance, allowlist, path; usable duration; beat/span/query/rank; reasoning; affect; staged risk; human presence; subject continuity; reviewed fallback; start/middle/end frames; opening-hook frames; carrier `placement_space`; crop safety |
| `current_set` | at selection | overlapping source window with another selected event |
| `manifest_declaration` | returned as `declarationsRequired`, audited at build | fallback or opening semantic fields the review did not record |
| `completion` | build-manifest / checkpoint | every planned event has exactly one row; typographic beats carry no footage |

Record the treatment you actually see in the review when it is not the literal one: `"fallback_level": "adjacent_metaphor", "fallback_reason": "..."` (a reason is required for every non-literal level). Admission then compares it with the planned level, and the manifest carries it; a build override cannot contradict it. Without it, the row defaults to `exact_literal` and a non-literal plan returns a `FALLBACK_UNDECLARED` declaration you must make at build or `reconcile-plan` with evidence. `human_presence` is never reconciled away to fit a clip: pick a reviewed alternate or reject and retry.
