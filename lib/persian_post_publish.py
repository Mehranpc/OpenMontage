"""Append-only helpers for observational post-publish performance evidence."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from schemas.artifacts import validate_artifact


class PostPublishPerformanceError(ValueError):
    """Raised when a performance history would lose identity or ordering."""


def append_performance_snapshot(
    record: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a validated copy with one later, unique snapshot appended.

    The input record is never mutated. This helper deliberately does not interpret
    performance or adjust hook thresholds; the artifact remains observational.
    """
    current = deepcopy(dict(record))
    validate_artifact("post_publish_performance", current)

    if current.get("calibration_mode") != "observational":
        raise PostPublishPerformanceError("post-publish calibration_mode must remain observational")

    candidate_snapshot = deepcopy(dict(snapshot))
    checkpoint = str(candidate_snapshot.get("checkpoint") or "").strip()
    if not checkpoint:
        raise PostPublishPerformanceError("snapshot checkpoint is required")

    existing = list(current.get("snapshots") or [])
    if any(str(item.get("checkpoint") or "") == checkpoint for item in existing):
        raise PostPublishPerformanceError(f"snapshot checkpoint {checkpoint!r} already exists")

    try:
        new_hours = float(candidate_snapshot["hours_since_publish"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PostPublishPerformanceError("snapshot hours_since_publish must be numeric") from exc

    if existing:
        try:
            previous_hours = float(existing[-1]["hours_since_publish"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PostPublishPerformanceError("existing snapshot hours_since_publish is invalid") from exc
        if new_hours <= previous_hours:
            raise PostPublishPerformanceError(
                f"snapshot hours_since_publish must increase: {new_hours} <= {previous_hours}"
            )

    updated = deepcopy(current)
    updated["snapshots"] = existing + [candidate_snapshot]
    validate_artifact("post_publish_performance", updated)
    return updated


__all__ = ["PostPublishPerformanceError", "append_performance_snapshot"]
