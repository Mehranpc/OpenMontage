"""Pipeline profile for the Persian footage path (#387).

``v2`` is today's geometry-coupled pipeline and stays the default (``DEFAULT_PROFILE``;
switching the default to v3 is an owner decision after the #387 Mac acceptance, never a
side effect of a merge). ``v3_staged`` is the
owner-approved forward-only architecture, where stage-1 footage admission is topic-level
and does not depend on text or watermark geometry. It stays opt-in: a plan that asks for
v3 is refused unless ``OPENMONTAGE_PIPELINE_PROFILE=v3_staged`` is set, so v2 gates
cannot be bypassed silently by writing a plan field. Each project is pinned to the
profile it was planned under and is never migrated in place (#387 increment 6).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROFILE_V2 = "v2"
PROFILE_V3 = "v3_staged"
PROFILES = (PROFILE_V2, PROFILE_V3)
OPT_IN_ENV = "OPENMONTAGE_PIPELINE_PROFILE"
DEFAULT_PROFILE = PROFILE_V2
TOPIC_MATCHES = ("on_topic", "off_topic")
#: Per-project pin (#387 increment 6). A project keeps the profile it was planned under;
#: existing projects are never migrated in place.
PIN_FILENAME = "pipeline_profile.json"
MIGRATION_REFUSED = "PIPELINE_PROFILE_MIGRATION_REFUSED"


class PipelineProfileError(ValueError):
    """A plan or review does not satisfy the selected pipeline profile."""


def plan_profile(scene_plan: Mapping[str, Any] | None) -> str:
    """The profile a scene plan declares in ``metadata.pipeline_profile`` (default v2)."""
    metadata = (scene_plan or {}).get("metadata") if isinstance(scene_plan, Mapping) else None
    raw = metadata.get("pipeline_profile") if isinstance(metadata, Mapping) else None
    if raw is None:
        return DEFAULT_PROFILE
    if raw not in PROFILES:
        raise PipelineProfileError(f"metadata.pipeline_profile must be one of {list(PROFILES)}")
    if raw == PROFILE_V3 and os.environ.get(OPT_IN_ENV) != PROFILE_V3:
        raise PipelineProfileError(
            f"pipeline_profile {PROFILE_V3!r} is not enabled; set {OPT_IN_ENV}={PROFILE_V3} "
            "(opt-in until the owner makes v3 the default after #387 acceptance)"
        )
    return str(raw)


def edit_profile(edit: Mapping[str, Any] | None) -> str:
    """The profile an edit declares in ``persian.pipelineProfile`` (default v2)."""
    persian = (edit or {}).get("persian") if isinstance(edit, Mapping) else None
    raw = persian.get("pipelineProfile") if isinstance(persian, Mapping) else None
    return plan_profile({"metadata": {"pipeline_profile": raw}} if raw is not None else None)


def read_profile_pin(project_dir: Any) -> dict[str, Any] | None:
    """The project's pinned profile record, or None for a project not yet pinned."""
    path = Path(project_dir) / PIN_FILENAME
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineProfileError(f"pipeline profile pin is unreadable: {path}") from exc
    if not isinstance(record, dict) or record.get("profile") not in PROFILES:
        raise PipelineProfileError(f"pipeline profile pin is malformed: {path}")
    return record


def require_pinned_profile(project_dir: Any, profile: str) -> str:
    """Refuse a profile that differs from the project's pin (no in-place migration)."""
    pin = read_profile_pin(project_dir)
    if pin is not None and pin["profile"] != profile:
        raise PipelineProfileError(
            f"[{MIGRATION_REFUSED}] this project is pinned to pipeline profile "
            f"{pin['profile']!r} but its plan declares {profile!r}; existing projects are not "
            "migrated in place. Start a fresh project for the other profile; earlier "
            "rejections are re-judged only by a fresh explicit review there."
        )
    return profile


def pin_project_profile(project_dir: Any, profile: str, *, phase: str | None = None) -> dict[str, Any]:
    """Pin ``profile`` once; an identical pin is idempotent, a different one is refused."""
    if profile not in PROFILES:
        raise PipelineProfileError(f"pipeline profile must be one of {list(PROFILES)}")
    require_pinned_profile(project_dir, profile)
    existing = read_profile_pin(project_dir)
    if existing is not None:
        return existing
    record = {"profile": profile, "pinnedAt": datetime.now(timezone.utc).isoformat(),
              "pinnedAtPhase": phase, "defaultProfile": DEFAULT_PROFILE}
    path = Path(project_dir) / PIN_FILENAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return record


def project_profile(project_dir: Any) -> str:
    """Profile of a project's effective scene plan, checked against its pin.

    No or unreadable plan falls back to the pin, then to the default. Reading never writes.
    """
    from lib.persian_scene_plan_source import ScenePlanUnreadable, load_effective_scene_plan

    try:
        plan = load_effective_scene_plan(project_dir)
    except ScenePlanUnreadable:
        plan = None
    if plan is None:
        pin = read_profile_pin(project_dir)
        return str(pin["profile"]) if pin is not None else DEFAULT_PROFILE
    return require_pinned_profile(project_dir, plan_profile(plan))


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
    "DEFAULT_PROFILE", "MIGRATION_REFUSED", "OPT_IN_ENV", "PIN_FILENAME", "PROFILES",
    "PROFILE_V2", "PROFILE_V3", "PipelineProfileError", "TOPIC_MATCHES", "pin_project_profile",
    "plan_profile", "project_profile", "read_profile_pin", "require_pinned_profile",
    "topic_review_diagnostics", "validate_topic_review",
]
