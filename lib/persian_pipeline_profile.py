"""Pipeline profile for the Persian footage path (#387).

``v2`` is today's geometry-coupled pipeline and stays the default. ``v3_staged`` is the
owner-approved forward-only architecture, where stage-1 footage admission is topic-level
and does not depend on text or watermark geometry. It is opt-in until the remaining #387
increments (stage locks, adaptive text, minimal watermark, range revision) are merged:
a plan that asks for v3 is refused unless ``OPENMONTAGE_PIPELINE_PROFILE=v3_staged`` is
set, so v2 gates cannot be bypassed silently by writing a plan field.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

PROFILE_V2 = "v2"
PROFILE_V3 = "v3_staged"
PROFILES = (PROFILE_V2, PROFILE_V3)
OPT_IN_ENV = "OPENMONTAGE_PIPELINE_PROFILE"
TOPIC_MATCHES = ("on_topic", "off_topic")


class PipelineProfileError(ValueError):
    """A plan or review does not satisfy the selected pipeline profile."""


def plan_profile(scene_plan: Mapping[str, Any] | None) -> str:
    """The profile a scene plan declares in ``metadata.pipeline_profile`` (default v2)."""
    metadata = (scene_plan or {}).get("metadata") if isinstance(scene_plan, Mapping) else None
    raw = metadata.get("pipeline_profile") if isinstance(metadata, Mapping) else None
    if raw is None:
        return PROFILE_V2
    if raw not in PROFILES:
        raise PipelineProfileError(f"metadata.pipeline_profile must be one of {list(PROFILES)}")
    if raw == PROFILE_V3 and os.environ.get(OPT_IN_ENV) != PROFILE_V3:
        raise PipelineProfileError(
            f"pipeline_profile {PROFILE_V3!r} is not enabled; set {OPT_IN_ENV}={PROFILE_V3} "
            "(opt-in until #387 stage locks land)"
        )
    return str(raw)


def project_profile(project_dir: Any) -> str:
    """Profile of a project's effective scene plan; no or unreadable plan means v2."""
    from lib.persian_scene_plan_source import ScenePlanUnreadable, load_effective_scene_plan

    try:
        return plan_profile(load_effective_scene_plan(project_dir))
    except ScenePlanUnreadable:
        return PROFILE_V2


def validate_topic_review(raw: object) -> dict[str, Any]:
    """Stage-1 topic-level review evidence (#387); shape only, never a verdict."""
    if not isinstance(raw, Mapping):
        raise PipelineProfileError("v3 review requires a topic_review object")
    result = {str(key): value for key, value in raw.items()}
    allowed = {"topic_match", "inappropriate", "placeholder_screen", "technical_usable", "observed"}
    unknown = sorted(set(result) - allowed)
    if unknown:
        raise PipelineProfileError(f"topic_review has unknown fields {unknown}")
    if result.get("topic_match") not in TOPIC_MATCHES:
        raise PipelineProfileError(f"topic_review.topic_match must be one of {list(TOPIC_MATCHES)}")
    for field in ("inappropriate", "placeholder_screen", "technical_usable"):
        if not isinstance(result.get(field), bool):
            raise PipelineProfileError(f"topic_review.{field} must be boolean")
    if not isinstance(result.get("observed"), str) or not result["observed"].strip():
        raise PipelineProfileError("topic_review.observed must state what the frames show")
    result["observed"] = result["observed"].strip()
    return result


def topic_review_diagnostics(review: object) -> list[tuple[str, str, Any, Any, str]]:
    """(code, field, expected, observed, reason) for each v3 stage-1 refusal."""
    if not isinstance(review, Mapping):
        return [("TOPIC_REVIEW_MISSING", "topic_review", "object", None,
                 "stage-1 footage needs topic_review evidence from the inspected frames")]
    found: list[tuple[str, str, Any, Any, str]] = []
    if review.get("topic_match") != "on_topic":
        found.append(("TOPIC_OFF", "topic_review.topic_match", "on_topic", review.get("topic_match"),
                      "the clip does not show the scene's subject, object or situation"))
    if review.get("inappropriate") is not False:
        found.append(("CONTENT_INAPPROPRIATE", "topic_review.inappropriate", False,
                      review.get("inappropriate"), "the clip is unsuitable for the audience"))
    if review.get("placeholder_screen") is not False:
        found.append(("PLACEHOLDER_SCREEN", "topic_review.placeholder_screen", False,
                      review.get("placeholder_screen"),
                      "a visible green/chroma or blank replacement screen is forbidden"))
    if review.get("technical_usable") is not True:
        found.append(("TECHNICAL_UNUSABLE", "topic_review.technical_usable", True,
                      review.get("technical_usable"), "the clip is not technically usable"))
    return found


__all__ = [
    "OPT_IN_ENV", "PROFILES", "PROFILE_V2", "PROFILE_V3", "PipelineProfileError",
    "TOPIC_MATCHES", "plan_profile", "topic_review_diagnostics", "validate_topic_review",
]
