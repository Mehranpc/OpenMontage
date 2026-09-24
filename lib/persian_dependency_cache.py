"""Dependency-scoped fingerprints for Persian production caches and review evidence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

DEPENDENCY_POLICY_VERSION = "1.0"


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def edit_visual_dependency_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    """Return render/layout inputs that are independent of narration/music mixing."""
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    visual = {
        str(key): value
        for key, value in persian.items()
        if str(key) not in {"audio", "musicTrack"}
    }
    return {"policyVersion": DEPENDENCY_POLICY_VERSION, "persian": visual}


def edit_audio_dependency_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    return {
        "policyVersion": DEPENDENCY_POLICY_VERSION,
        "audio": persian.get("audio"),
        "musicTrack": persian.get("musicTrack"),
    }


def edit_final_review_dependency_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    """Bind final review to all edit inputs that can change rendered bytes/meaning."""
    return {
        "policyVersion": DEPENDENCY_POLICY_VERSION,
        "visual": edit_visual_dependency_payload(edit),
        "audio": edit_audio_dependency_payload(edit),
    }


def edit_visual_dependency_digest(edit: Mapping[str, Any]) -> str:
    return _digest(edit_visual_dependency_payload(edit))


def edit_audio_dependency_digest(edit: Mapping[str, Any]) -> str:
    return _digest(edit_audio_dependency_payload(edit))


def edit_final_review_dependency_digest(edit: Mapping[str, Any]) -> str:
    return _digest(edit_final_review_dependency_payload(edit))


def asset_visual_dependency_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return only asset fields that can change subject-region frame geometry."""
    keys = (
        "visual_event_id", "beat_id", "scene_id", "path", "source_id",
        "source_in_seconds", "source_window_end_seconds", "duration_seconds",
        "width", "height",
    )
    rows: list[Any] = []
    raw_assets = manifest.get("assets")
    if isinstance(raw_assets, list):
        for raw in raw_assets:
            if isinstance(raw, Mapping):
                rows.append({key: raw.get(key) for key in keys if key in raw})
            else:
                rows.append(raw)
    else:
        rows = [raw_assets]
    return {
        "policyVersion": DEPENDENCY_POLICY_VERSION,
        "assets": rows,
    }


def asset_visual_dependency_digest(manifest: Mapping[str, Any]) -> str:
    return _digest(asset_visual_dependency_payload(manifest))


def scene_geometry_dependency_digest(scene_plan: Mapping[str, Any]) -> str:
    # Scene semantics (including subject/intent) influence what a reviewer must
    # protect, even when the selected source window itself is unchanged.
    return _digest({
        "policyVersion": DEPENDENCY_POLICY_VERSION,
        "scenePlan": dict(scene_plan),
    })


__all__ = [
    "DEPENDENCY_POLICY_VERSION",
    "asset_visual_dependency_digest",
    "edit_audio_dependency_digest",
    "edit_audio_dependency_payload",
    "edit_final_review_dependency_digest",
    "edit_final_review_dependency_payload",
    "edit_visual_dependency_digest",
    "edit_visual_dependency_payload",
    "scene_geometry_dependency_digest",
]
