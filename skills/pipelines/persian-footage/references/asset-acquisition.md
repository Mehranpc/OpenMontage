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

Pixabay music is the approved provider. Select instrumental audio at least as long as delivery. Persist path, source, licence name/URL/download date, attribution, and Content-ID risk. Narrated mode requires music or explicit deliberate silence. Unknown risk needs acknowledgement; high risk is refused.