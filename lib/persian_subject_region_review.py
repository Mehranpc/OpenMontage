"""Fail-closed validation for reviewed Persian footage subject/action regions."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class SubjectRegionReviewError(ValueError):
    """Raised when subject-region review evidence is missing or malformed."""


def _number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubjectRegionReviewError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise SubjectRegionReviewError(f"{label} must be a finite number")
    return result


def _normalize_region(raw: object, *, shot_id: str, index: int) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise SubjectRegionReviewError(
            f"shot_regions[{shot_id}].avoidRegions[{index}] must be an object"
        )
    prefix = f"shot_regions[{shot_id}].avoidRegions[{index}]"
    x = _number(raw.get("x"), label=f"{prefix}.x")
    y = _number(raw.get("y"), label=f"{prefix}.y")
    w = _number(raw.get("w"), label=f"{prefix}.w")
    h = _number(raw.get("h"), label=f"{prefix}.h")
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
        raise SubjectRegionReviewError(
            f"{prefix} must be a positive normalized screen-space rectangle inside 0..1"
        )
    region: dict[str, float] = {"x": x, "y": y, "w": w, "h": h}
    has_start = "startSeconds" in raw
    has_end = "endSeconds" in raw
    if has_start != has_end:
        raise SubjectRegionReviewError(
            f"{prefix} must provide startSeconds and endSeconds together"
        )
    if has_start:
        start = _number(raw.get("startSeconds"), label=f"{prefix}.startSeconds")
        end = _number(raw.get("endSeconds"), label=f"{prefix}.endSeconds")
        if start < 0 or end <= start:
            raise SubjectRegionReviewError(
                f"{prefix} timing must satisfy 0 <= startSeconds < endSeconds"
            )
        region["startSeconds"] = start
        region["endSeconds"] = end
    return region


def validate_subject_region_review_evidence(
    evidence: Mapping[str, Any], *, expected_shot_ids: Sequence[str] | None = None
) -> dict[str, Any]:
    """Normalize reviewed per-shot geometry without inventing empty/clear regions.

    An empty ``avoidRegions`` list is legal only when start/middle/end review is
    explicitly present and true; it means the reviewer inspected the full selected
    window and found no conservative subject/action envelope to protect.
    """
    if not isinstance(evidence, Mapping):
        raise SubjectRegionReviewError("subject-region review evidence must be an object")
    rows = evidence.get("shot_regions")
    if not isinstance(rows, list) or not rows:
        raise SubjectRegionReviewError("subject-region review requires non-empty shot_regions")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise SubjectRegionReviewError(f"shot_regions[{index}] must be an object")
        shot_id = str(raw.get("shot_id") or "").strip()
        if not shot_id:
            raise SubjectRegionReviewError(f"shot_regions[{index}].shot_id must be non-empty")
        if shot_id in seen:
            raise SubjectRegionReviewError(f"duplicate reviewed shot id: {shot_id}")
        seen.add(shot_id)

        frame = raw.get("frame_review")
        if not isinstance(frame, Mapping):
            raise SubjectRegionReviewError(f"shot_regions[{shot_id}].frame_review is required")
        for key in ("start", "middle", "end"):
            if frame.get(key) is not True:
                raise SubjectRegionReviewError(
                    f"shot_regions[{shot_id}].frame_review.{key} must be true"
                )
        observed = str(frame.get("observed") or "").strip()
        if not observed:
            raise SubjectRegionReviewError(
                f"shot_regions[{shot_id}].frame_review.observed must be non-empty"
            )

        regions = raw.get("avoidRegions")
        if not isinstance(regions, list):
            raise SubjectRegionReviewError(
                f"shot_regions[{shot_id}].avoidRegions must be an array"
            )
        normalized.append({
            "shot_id": shot_id,
            "avoidRegions": [
                _normalize_region(region, shot_id=shot_id, index=region_index)
                for region_index, region in enumerate(regions)
            ],
            "frame_review": {
                "start": True,
                "middle": True,
                "end": True,
                "observed": observed,
            },
        })

    if expected_shot_ids is not None:
        expected = [str(item).strip() for item in expected_shot_ids]
        if any(not item for item in expected) or len(set(expected)) != len(expected):
            raise SubjectRegionReviewError("expected_shot_ids must be unique non-empty ids")
        missing = [item for item in expected if item not in seen]
        unexpected = [item for item in seen if item not in set(expected)]
        if missing:
            raise SubjectRegionReviewError(
                f"missing reviewed shot ids: {', '.join(missing)}"
            )
        if unexpected:
            raise SubjectRegionReviewError(
                f"unexpected reviewed shot ids: {', '.join(sorted(unexpected))}"
            )

    return {"shot_regions": normalized}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Persian subject-region review evidence")
    parser.add_argument("evidence_json")
    parser.add_argument("--expected-shot-id", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.evidence_json).read_text(encoding="utf-8"))
        normalized = validate_subject_region_review_evidence(
            payload,
            expected_shot_ids=args.expected_shot_id or None,
        )
    except (OSError, json.JSONDecodeError, SubjectRegionReviewError) as exc:
        print(f"subject-region review refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(normalized, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
