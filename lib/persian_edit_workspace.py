"""Draft/probe/promotion lifecycle for Persian edit decisions.

Failed probes never overwrite the canonical edit artifact. Promotion is digest-bound
to the exact draft that produced a passing aggregate preflight report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from lib.paths import REPO_ROOT
from lib.persian_audio_policy import materialize_loudness_aware_mix
from lib.persian_dependency_cache import (
    edit_audio_dependency_payload, edit_final_review_dependency_payload,
    edit_visual_dependency_payload,
)
from lib.persian_hook_quality import HOOK_TIMING_POLICY_VERSION
from lib.persian_geometric_precheck import geometric_hard_region_precheck
from lib.persian_preflight import (
    PREFLIGHT_POLICY_VERSION, aggregate_preflight_edit_decisions, extract_edit_decisions,
)
from lib.persian_recovery_policy import recovery_policy_for_issue, shot_local_recovery_plan
from lib.persian_asset_workspace import (
    PersianAssetWorkspaceError,
    asset_workspace_status,
    validate_edit_asset_bindings,
    validate_edit_asset_bindings_against_manifest,
)
from lib.persian_project_workspace import workspace_directory

_ATTEMPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class PersianEditWorkspaceError(ValueError):
    pass


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def artifact_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(_json_bytes(value))
    temp.replace(path)


def _attempt(attempt_id: str) -> str:
    if not _ATTEMPT_RE.fullmatch(attempt_id):
        raise PersianEditWorkspaceError(
            "attempt_id must be 1-80 ASCII letters/digits plus ._- characters"
        )
    return attempt_id


def _paths(project_dir: Path, attempt_id: str) -> tuple[Path, Path, Path]:
    root = project_dir.expanduser().resolve()
    attempt = _attempt(attempt_id)
    draft = root / ".drafts" / "edit" / attempt / "edit_decisions.json"
    report = root / ".preflight" / "edit" / attempt / "preflight_report.json"
    canonical = root / "artifacts" / "edit_decisions.json"
    return draft, report, canonical


def _cache_path(project_dir: Path, digest: str) -> Path:
    return project_dir.expanduser().resolve() / ".preflight" / "cache" / "edit" / f"{digest}.json"


def _valid_cached_report(
    value: object, *, digest: str, dependency_digests: Mapping[str, str] | None = None
) -> bool:
    return (
        isinstance(value, dict)
        and value.get("artifactSha256") == digest
        and value.get("policyVersion") == PREFLIGHT_POLICY_VERSION
        and (
            dependency_digests is None
            or value.get("dependencyDigests") == dict(dependency_digests)
        )
        and isinstance(value.get("ok"), bool)
    )


def _convergence_root(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".convergence" / "edit"


def _candidate_path(project_dir: Path, attempt_id: str) -> Path:
    return _convergence_root(project_dir) / _attempt(attempt_id) / "candidate.json"


def _unresolved_path(project_dir: Path) -> Path:
    return _convergence_root(project_dir) / "unresolved.json"


def _component_cache_path(project_dir: Path, component: str, digest: str) -> Path:
    return (
        project_dir.expanduser().resolve()
        / ".preflight"
        / "cache"
        / "components"
        / component
        / f"{digest}.json"
    )


def _stable_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _shot_subset(shots: object, keys: set[str]) -> list[dict[str, Any]]:
    if not isinstance(shots, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in shots:
        if isinstance(raw, Mapping):
            result.append({key: raw.get(key) for key in sorted(keys) if key in raw})
    return result


def _moment_subset(moments: object, keys: set[str]) -> list[dict[str, Any]]:
    if not isinstance(moments, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in moments:
        if isinstance(raw, Mapping):
            result.append({key: raw.get(key) for key in sorted(keys) if key in raw})
    return result


def _retention_dependency_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    return {
        "durationSeconds": persian.get("durationSeconds"),
        "shots": _shot_subset(
            persian.get("shots"),
            {
                "id", "startSeconds", "endSeconds", "transitionIn", "visualEventId",
                "changeType", "narrativeRole", "humanPresence",
            },
        ),
        "moments": _moment_subset(
            persian.get("moments"), {"id", "kind", "startSeconds", "endSeconds"}
        ),
        "typographicBeats": _moment_subset(
            persian.get("typographicBeats"), {"id", "startSeconds", "endSeconds"}
        ),
    }


def _hook_dependency_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    metadata = edit.get("metadata") if isinstance(edit.get("metadata"), Mapping) else {}
    hook_moments = []
    for raw in persian.get("moments") or []:
        if isinstance(raw, Mapping) and raw.get("kind") == "hook":
            hook_moments.append({
                **{
                    key: raw.get(key)
                    for key in (
                        "id", "kind", "startSeconds", "endSeconds",
                        "userAuthoredShortHook",
                    )
                    if key in raw
                },
                "text": _segment_copy_text(raw.get("segments")),
            })
    return {
        "durationSeconds": persian.get("durationSeconds"),
        "platformTarget": persian.get("platformTarget"),
        "shots": _shot_subset(
            persian.get("shots"),
            {
                "id", "startSeconds", "endSeconds", "narrativeRole", "changeType",
                "visualEventId", "humanPresence", "openingSemanticMatch", "semanticRole",
                "semanticDirection", "selectionReason",
            },
        ),
        "hookMoments": hook_moments,
        "typographicBeats": _moment_subset(
            persian.get("typographicBeats"), {"id", "startSeconds", "endSeconds"}
        ),
        "hookQuality": metadata.get("hookQuality"),
        "targetPlatform": metadata.get("targetPlatform") or metadata.get("target_platform"),
    }


_COMPONENT_IMPLEMENTATION_PATHS: dict[str, tuple[str, ...]] = {
    "retention": (
        "lib/persian_retention.py",
        "lib/persian_text.py",
    ),
    "hook": (
        "lib/persian_hook_quality.py",
        "lib/persian_text.py",
    ),
    # Browser evidence is the expensive executable-layout result. Bind it to the
    # whole Persian compose/render implementation and its pinned runtime inputs,
    # not only to edit JSON. A renderer/layout change must never reuse pixels or
    # geometry audited by an older implementation.
    "browser": (
        "lib/persian_edit_workspace.py",
        "lib/persian_preflight.py",
        "lib/persian_edit_contract.py",
        "lib/persian_sync.py",
        "lib/persian_film_type.py",
        "lib/persian_geometric_precheck.py",
        "lib/persian_captions.py",
        "lib/persian_srt.py",
        "lib/persian_text.py",
        "tools/video/persian_compose_script_aligned.py",
        "remotion-composer/scripts/prepare-persian-film-type.mjs",
        "remotion-composer/src/persian",
        "remotion-composer/package.json",
        "remotion-composer/package-lock.json",
        "styles/persian-footage",
        "requirements.txt",
    ),
}


def _implementation_tree_digest(relative_paths: Sequence[str]) -> str:
    """Hash committed implementation bytes that can affect one preflight component."""
    files: dict[str, Path] = {}
    for raw in relative_paths:
        relative = Path(raw)
        target = (REPO_ROOT / relative).resolve()
        if target.is_file():
            files[target.relative_to(REPO_ROOT).as_posix()] = target
            continue
        if target.is_dir():
            for child in target.rglob("*"):
                if child.is_file():
                    files[child.resolve().relative_to(REPO_ROOT).as_posix()] = child.resolve()
            continue
        raise PersianEditWorkspaceError(
            f"preflight implementation dependency is missing: {relative.as_posix()}"
        )

    digest = hashlib.sha256()
    for relative, path in sorted(files.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _component_implementation_digests() -> dict[str, str]:
    """Return deterministic source/runtime identities for selectively cached checks."""
    return {
        component: _implementation_tree_digest(paths)
        for component, paths in _COMPONENT_IMPLEMENTATION_PATHS.items()
    }


def _hook_authority_dependency_payload(
    hook_authority: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(hook_authority, Mapping):
        return None
    return {
        key: hook_authority.get(key)
        for key in ("mode", "authoritative", "sha256", "source", "revision_cycle")
        if hook_authority.get(key) is not None
    }


def _dependency_digests(
    edit: Mapping[str, Any], *, hook_authority: Mapping[str, Any] | None = None
) -> dict[str, str]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    implementation = _component_implementation_digests()
    payloads = {
        "retention": {
            "version": "retention-v1",
            "implementationSha256": implementation["retention"],
            "deps": _retention_dependency_payload(edit),
        },
        "hook": {
            "version": "hook-v2",
            # Hook-quality evidence is timing-policy dependent. Carrying the policy
            # identity in the dependency digest means a policy revision invalidates
            # cached hook evidence instead of silently reusing a stale verdict.
            "timingPolicyVersion": HOOK_TIMING_POLICY_VERSION,
            "implementationSha256": implementation["hook"],
            "deps": _hook_dependency_payload(edit),
            "authority": _hook_authority_dependency_payload(hook_authority),
        },
        "browser": {
            "version": "browser-v1",
            "implementationSha256": implementation["browser"],
            "deps": edit_visual_dependency_payload(edit),
        },
        "audio": {
            "version": "audio-v1",
            "deps": edit_audio_dependency_payload(edit),
        },
        "final_review": {
            "version": "final-review-v1",
            "deps": edit_final_review_dependency_payload(edit),
        },
    }
    return {
        name: _stable_digest({"policyVersion": PREFLIGHT_POLICY_VERSION, **payload})
        for name, payload in payloads.items()
    }


def _semantic_segments(value: object) -> list[Any]:
    """Return segment semantics without authored reveal timing.

    `revealAfterSeconds` is a timeline instruction. Including it in the copy digest
    made a timing-only repair look like a semantic rewrite and prevented bounded
    Film Type recovery from repairing its own browser timing diagnostic.
    """
    result: list[Any] = []
    for raw in value or [] if isinstance(value, list) else []:
        if isinstance(raw, Mapping):
            result.append({
                str(key): item
                for key, item in raw.items()
                if str(key) != "revealAfterSeconds"
            })
        else:
            result.append(raw)
    return result


def _segment_copy_text(value: object) -> str:
    """Return painted segment text while ignoring visual segmentation metadata.

    Film Type 2.16 explicitly allows a measured line-plan recovery to re-segment
    the same viewer-visible phrase. Segment roles, phrase locks, and boundaries
    are typography/layout decisions; changing the actual words or punctuation is
    still a copy change. Normalise only the inter-segment separator so moving a
    boundary does not masquerade as a rewrite.
    """
    parts: list[str] = []
    for raw in value or [] if isinstance(value, list) else []:
        if isinstance(raw, Mapping):
            text = raw.get("text")
            if text is not None:
                cleaned = str(text).strip()
                if cleaned:
                    parts.append(cleaned)
        elif raw is not None:
            cleaned = str(raw).strip()
            if cleaned:
                parts.append(cleaned)
    return " ".join(parts)


def _copy_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    moments = []
    for raw in persian.get("moments") or []:
        if isinstance(raw, Mapping):
            moments.append({
                "id": raw.get("id"),
                "text": _segment_copy_text(raw.get("segments")),
            })
    captions = []
    for raw in persian.get("captions") or []:
        if isinstance(raw, Mapping):
            captions.append({"id": raw.get("id"), "text": raw.get("text")})
    beats = []
    for raw in persian.get("typographicBeats") or []:
        if isinstance(raw, Mapping):
            beats.append({
                "id": raw.get("id"),
                "text": raw.get("text"),
                "segmentText": _segment_copy_text(raw.get("segments")),
            })
    return {"moments": moments, "captions": captions, "typographicBeats": beats}


def _typography_payload(edit: Mapping[str, Any]) -> list[dict[str, Any]]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    metadata = edit.get("metadata") if isinstance(edit.get("metadata"), Mapping) else {}
    result: list[dict[str, Any]] = []
    ignored = {"id", "kind", "startSeconds", "endSeconds", "segments", "text"}
    for collection in ("moments", "typographicBeats"):
        for raw in persian.get(collection) or []:
            if not isinstance(raw, Mapping):
                continue
            style = {
                str(key): value
                for key, value in raw.items()
                if key not in ignored
                and any(
                    token in str(key).lower()
                    for token in ("recipe", "layout", "typograph", "font", "style", "line", "placement")
                )
            }
            presentation = raw.get("presentation")
            if isinstance(presentation, Mapping) and "recipeId" in presentation:
                style["presentation.recipeId"] = presentation.get("recipeId")
            exact_text = raw.get("exactText")
            if exact_text is not None:
                style["exactText"] = exact_text
            segments = _semantic_segments(raw.get("segments"))
            if segments:
                style["linePlan"] = segments
            if style:
                result.append({"collection": collection, "id": raw.get("id"), **style})
    semantic_poster_stack = metadata.get("semanticPosterStack")
    if semantic_poster_stack is not None:
        result.append({
            "collection": "metadata",
            "id": "semanticPosterStack",
            "value": semantic_poster_stack,
        })
    return result


def _asset_payload(edit: Mapping[str, Any]) -> list[dict[str, Any]]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    result: list[dict[str, Any]] = []
    tokens = ("src", "source", "asset", "provider", "clip", "query", "crop", "window", "media", "path", "url", "video", "attribution")
    for raw in persian.get("shots") or []:
        if not isinstance(raw, Mapping):
            continue
        selected = {
            str(key): value
            for key, value in raw.items()
            if any(token in str(key).lower() for token in tokens)
        }
        result.append({"id": raw.get("id"), **selected})
    return result


def _asset_changed_shot_ids(
    base_edit: Mapping[str, Any] | None, edit: Mapping[str, Any]
) -> list[str]:
    if base_edit is None:
        return []
    before = {str(item.get("id") or ""): item for item in _asset_payload(base_edit)}
    after = {str(item.get("id") or ""): item for item in _asset_payload(edit)}
    return sorted(
        shot_id for shot_id in set(before) | set(after)
        if shot_id and before.get(shot_id) != after.get(shot_id)
    )


def _scene_payload(edit: Mapping[str, Any]) -> list[dict[str, Any]]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    result: list[dict[str, Any]] = []
    keys = {
        "id", "visualEventId", "changeType", "narrativeRole", "humanPresence",
        "semanticRole", "semanticDirection", "selectionReason", "openingSemanticMatch",
        "camera", "showsSubject",
    }
    for raw in persian.get("shots") or []:
        if isinstance(raw, Mapping):
            result.append({key: raw.get(key) for key in sorted(keys) if key in raw})
    return result


def _timeline_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    keys = {"id", "kind", "startSeconds", "endSeconds"}

    def timed_moments(value: object) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in value or [] if isinstance(value, list) else []:
            if not isinstance(raw, Mapping):
                continue
            item = {str(key): raw.get(key) for key in keys if key in raw}
            # Timeline semantics are the reveal groups, not how many visual text
            # segments happen to share each group. A Film Type line-plan recovery
            # may re-segment simultaneous hook copy without changing timing.
            item["segmentReveals"] = sorted({
                float(segment.get("revealAfterSeconds", 0))
                for segment in (raw.get("segments") or [])
                if isinstance(segment, Mapping)
            })
            result.append(item)
        return result

    return {
        "durationSeconds": persian.get("durationSeconds"),
        "shots": _shot_subset(persian.get("shots"), {"id", "startSeconds", "endSeconds"}),
        "moments": timed_moments(persian.get("moments")),
        "typographicBeats": timed_moments(persian.get("typographicBeats")),
        "captions": _moment_subset(persian.get("captions"), {"id", "startSeconds", "endSeconds"}),
    }


def _hook_scope_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    return _hook_dependency_payload(edit)


def _unclassified_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    """Capture edit fields not owned by a named convergence mutation scope."""
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    metadata = edit.get("metadata") if isinstance(edit.get("metadata"), Mapping) else {}
    root_unknown = {
        str(key): value
        for key, value in edit.items()
        if key not in {"persian", "metadata"}
    }
    metadata_unknown = {
        str(key): value
        for key, value in metadata.items()
        if key not in {
            "hookQuality", "targetPlatform", "target_platform", "semanticPosterStack",
            # The hook/caption handoff is caption semantics, not an unowned field.
            # Leaving it here put the one repair CAPTION_CONTINUITY exists to make
            # outside every scope that class is allowed to change (#152).
            "hookCaptionHandoff",
        }
    }
    known_persian = {
        "durationSeconds", "platformTarget", "shots", "moments", "typographicBeats",
        "captions", "audio", "watermark",
    }
    persian_unknown = {
        str(key): value for key, value in persian.items() if key not in known_persian
    }

    asset_tokens = (
        "src", "source", "asset", "provider", "clip", "query", "crop",
        "window", "media", "path", "url", "video", "attribution",
    )
    known_shot = {
        "id", "startSeconds", "endSeconds", "visualEventId", "changeType",
        "narrativeRole", "humanPresence", "semanticRole", "semanticDirection",
        "selectionReason", "openingSemanticMatch", "avoidRegions", "camera", "showsSubject",
    }
    shot_unknown: list[dict[str, Any]] = []
    for raw in persian.get("shots") or []:
        if not isinstance(raw, Mapping):
            continue
        extras = {
            str(key): value
            for key, value in raw.items()
            if key not in known_shot
            and not any(token in str(key).lower() for token in asset_tokens)
        }
        if extras:
            shot_unknown.append({"id": raw.get("id"), **extras})

    style_tokens = ("recipe", "layout", "typograph", "font", "style", "line", "placement")
    known_moment = {
        "id", "kind", "startSeconds", "endSeconds", "segments", "text",
        "userAuthoredShortHook", "presentation", "exactText",
    }
    moment_unknown: list[dict[str, Any]] = []
    for collection in ("moments", "typographicBeats"):
        for raw in persian.get(collection) or []:
            if not isinstance(raw, Mapping):
                continue
            extras = {
                str(key): value
                for key, value in raw.items()
                if key not in known_moment
                and not any(token in str(key).lower() for token in style_tokens)
            }
            presentation = raw.get("presentation")
            if isinstance(presentation, Mapping):
                presentation_unknown = {
                    str(key): value
                    for key, value in presentation.items()
                    if key != "recipeId"
                }
                if presentation_unknown:
                    extras["presentation"] = presentation_unknown
            if extras:
                moment_unknown.append({"collection": collection, "id": raw.get("id"), **extras})

    return {
        "root": root_unknown,
        "metadata": metadata_unknown,
        "persian": persian_unknown,
        "shots": shot_unknown,
        "moments": moment_unknown,
    }


def _scope_digests(edit: Mapping[str, Any]) -> dict[str, str]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    scope_payloads: dict[str, Any] = {
        "hook": _hook_scope_payload(edit),
        "captions": {
            "cues": persian.get("captions") or [],
            # Owned here so a handoff repair registers as a caption change rather
            # than as an unclassified one (#152).
            "handoff": (edit.get("metadata") or {}).get("hookCaptionHandoff")
            if isinstance(edit.get("metadata"), Mapping)
            else None,
        },
        "timeline": _timeline_payload(edit),
        "watermark": persian.get("watermark") or {},
        "typography": _typography_payload(edit),
        "assets": _asset_payload(edit),
        "scenes": _scene_payload(edit),
        "audio_mix": persian.get("audio") or {},
        "copy": _copy_payload(edit),
        "subject_regions": [
            {"id": raw.get("id"), "avoidRegions": raw.get("avoidRegions") or []}
            for raw in (persian.get("shots") or [])
            if isinstance(raw, Mapping)
        ],
        "unclassified": _unclassified_payload(edit),
    }
    return {name: _stable_digest(value) for name, value in scope_payloads.items()}


def _changed_scopes(base_edit: Mapping[str, Any] | None, edit: Mapping[str, Any]) -> list[str]:
    if base_edit is None:
        return []
    before = _scope_digests(base_edit)
    after = _scope_digests(edit)
    return sorted(name for name in after if before.get(name) != after.get(name))


def _scoped_reacquisition_hint(
    project_dir: Path, edit: Mapping[str, Any], code: str, details: Mapping[str, Any]
) -> str:
    """Name the bounded repair when same-phase asset options are exhausted (#152).

    A placement refusal whose affected shots have no reusable reviewed candidate is
    a footage problem, not an editorial one. The scoped re-acquisition path already
    exists in the workflow, but nothing surfaced it here, so the refusal read as a
    dead end and the run stopped for a human. Naming the bounded repair makes the
    next step mechanical.
    """
    if not code:
        return ""
    try:
        plan = shot_local_recovery_plan(
            {"code": code, "details": dict(details)},
            edit,
            asset_workspace_status(project_dir),
        )
    except (ValueError, PersianAssetWorkspaceError, OSError):
        return ""
    if plan.get("decision") != "scoped_asset_reacquisition":
        return ""
    shots = ", ".join(str(item) for item in (plan.get("reacquireShotIds") or []))
    events = ", ".join(str(item) for item in (plan.get("reacquireVisualEventIds") or []))
    return (
        "\n  bounded repair: same-phase asset options are exhausted for "
        f"shot(s) {shots} (visual event(s) {events}); scoped re-acquisition is "
        "allowed - send back to acquire_assets with this code and those shot ids"
    )


_NAMED_FIELD_KEYS = ("field", "path", "jsonPointer", "json_pointer", "contractField")


def _named_contract_field(issue: Mapping[str, Any]) -> str:
    """The contract field a diagnostic reports as the thing to repair."""
    details = issue.get("details") if isinstance(issue.get("details"), Mapping) else {}
    for source in (issue, details):
        for key in _NAMED_FIELD_KEYS:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _field_within_named(declared: str, named: str) -> bool:
    """Whether a declared field names the same contract field the diagnostic reports.

    Accepts the same field, or a dotted/slashed path into it, so a diagnostic that
    reports a nested location still matches a candidate declaring its parent field.
    """
    left = str(declared or "").strip().strip("/")
    right = str(named or "").strip().strip("/")
    if not left or not right:
        return False
    if left == right:
        return True
    return left.startswith(f"{right}.") or left.startswith(f"{right}/") or (
        right.startswith(f"{left}.") or right.startswith(f"{left}/")
    )


def _allowed_scopes(mutation_surface: list[str]) -> set[str]:
    allowed: set[str] = set()
    for item in mutation_surface:
        value = str(item)
        if value == "diagnostic.named_contract_field":
            return {"*"}
        if value.startswith("hook.semantic_copy"):
            allowed.update({"hook", "copy"})
        elif value.startswith("hook.semantic_evidence"):
            allowed.add("hook")
        elif value.startswith("hook."):
            allowed.update({"hook", "timeline"})
        elif value.startswith("opening."):
            allowed.update({"assets", "scenes"})
        elif value.startswith("captions."):
            allowed.update({"captions", "copy", "timeline"})
        elif value.startswith("timeline."):
            allowed.add("timeline")
        elif value.startswith("watermark."):
            allowed.add("watermark")
        elif value in {"typography.recipe", "typography.line_plan"}:
            allowed.add("typography")
        elif value.startswith("typography."):
            allowed.update({"typography", "timeline"})
        elif value.startswith("assets."):
            allowed.add("assets")
        elif value.startswith("scenes."):
            allowed.add("scenes")
        elif value.startswith("subject_regions."):
            allowed.add("subject_regions")
        elif value.startswith("runtime."):
            pass
    return allowed


def _load_draft(project_dir: Path, attempt_id: str) -> dict[str, Any]:
    draft, _, _ = _paths(project_dir, attempt_id)
    if not draft.is_file():
        raise PersianEditWorkspaceError(f"edit draft does not exist: {draft}")
    value = json.loads(draft.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PersianEditWorkspaceError("edit draft is not a JSON object")
    return value


def load_convergence_candidate(project_dir: Path, attempt_id: str) -> dict[str, Any]:
    path = _candidate_path(project_dir, attempt_id)
    if not path.is_file():
        raise PersianEditWorkspaceError(f"convergence candidate does not exist: {attempt_id}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PersianEditWorkspaceError("convergence candidate manifest is invalid")
    return value


def _candidate_manifests(project_dir: Path) -> list[dict[str, Any]]:
    root = _convergence_root(project_dir)
    if not root.is_dir():
        return []
    manifests: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/candidate.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            manifests.append(value)
    return manifests


def _write_unresolved(
    project_dir: Path,
    *,
    reason: str,
    recovery_class: str | None,
    attempts_used: int,
    max_attempts: int | None,
    global_used: int,
    global_max: int,
    diagnostic_issue: Mapping[str, Any] | None,
    revision_cycle: int,
) -> dict[str, Any]:
    unresolved = {
        "version": "1.0",
        "status": "needs_revision",
        "reason": reason,
        "recoveryClass": recovery_class,
        "attemptsUsed": attempts_used,
        "maxAttempts": max_attempts,
        "globalCandidatesUsed": global_used,
        "globalMaxCandidates": global_max,
        "revisionCycle": int(revision_cycle),
        "outcome": "needs_human_editorial_revision",
        "unresolvedDiagnostics": [dict(diagnostic_issue)] if isinstance(diagnostic_issue, Mapping) else [],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(_unresolved_path(project_dir), unresolved)
    return unresolved


def convergence_status(
    project_dir: Path, *, revision_cycle: int | None = None
) -> dict[str, Any]:
    manifests = _candidate_manifests(project_dir)
    if revision_cycle is not None:
        manifests = [
            item for item in manifests
            if int(item.get("revisionCycle") or 0) == int(revision_cycle)
        ]
    unresolved = None
    path = _unresolved_path(project_dir)
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            if revision_cycle is None or int(value.get("revisionCycle") or 0) == int(revision_cycle):
                unresolved = value
    promoted = [item for item in manifests if item.get("disposition") == "promoted"]
    promoted.sort(key=lambda item: str(item.get("promotedAt") or item.get("updatedAt") or ""))
    return {
        "version": "1.0",
        "revisionCycle": revision_cycle,
        "status": "needs_revision" if unresolved else "active",
        "candidateCount": len(manifests),
        "candidateIds": [str(item.get("candidateId")) for item in manifests],
        "promotedCandidateId": str(promoted[-1].get("candidateId")) if promoted else None,
        "unresolved": unresolved,
    }


def mark_blocked_convergence_exhausted(
    project_dir: Path,
    attempt_id: str,
    *,
    max_candidates: int,
    revision_cycle: int,
) -> dict[str, Any] | None:
    """Persist the terminal stop when the final allowed candidate is blocked.

    Convergence used to persist ``needs_revision`` only when callers attempted to
    stage one candidate *past* the global budget. That made the valid boundary
    state (N/N candidates, last one blocked) remain falsely active until an
    illegal extra staging request was made. Terminalize at the completed blocked
    preflight instead, without creating another candidate.
    """
    if max_candidates < 1:
        raise PersianEditWorkspaceError("max_candidates must be positive")
    manifest = load_convergence_candidate(project_dir, attempt_id)
    if int(manifest.get("revisionCycle") or 0) != int(revision_cycle):
        return None
    if manifest.get("disposition") != "blocked":
        return None

    manifests = [
        item for item in _candidate_manifests(project_dir)
        if int(item.get("revisionCycle") or 0) == int(revision_cycle)
    ]
    if len(manifests) < max_candidates:
        return None

    diagnostics = manifest.get("producedDiagnostics")
    diagnostic_issue = (
        diagnostics[0]
        if isinstance(diagnostics, list)
        and diagnostics
        and isinstance(diagnostics[0], Mapping)
        else None
    )
    recovery_class = None
    max_attempts = None
    if isinstance(diagnostic_issue, Mapping):
        recovery_class = str(diagnostic_issue.get("recoveryClass") or "") or None
        try:
            plan = recovery_policy_for_issue(diagnostic_issue)
        except Exception:
            plan = None
        if isinstance(plan, Mapping):
            recovery_class = str(plan.get("recoveryClass") or recovery_class or "") or None
            if plan.get("maxAttempts") is not None:
                max_attempts = int(plan["maxAttempts"])

    attempts_used = (
        sum(1 for item in manifests if item.get("recoveryClass") == recovery_class)
        if recovery_class else 0
    )
    return _write_unresolved(
        project_dir,
        reason="global_candidate_budget_exhausted",
        recovery_class=recovery_class,
        attempts_used=attempts_used,
        max_attempts=max_attempts,
        global_used=len(manifests),
        global_max=max_candidates,
        diagnostic_issue=diagnostic_issue,
        revision_cycle=revision_cycle,
    )


def compare_edit_candidates(project_dir: Path, left_attempt_id: str, right_attempt_id: str) -> dict[str, Any]:
    left = _load_draft(project_dir, left_attempt_id)
    right = _load_draft(project_dir, right_attempt_id)
    return {
        "leftCandidateId": left_attempt_id,
        "rightCandidateId": right_attempt_id,
        "leftArtifactSha256": artifact_sha256(left),
        "rightArtifactSha256": artifact_sha256(right),
        "changedScopes": _changed_scopes(left, right),
    }


def _load_component_cache(project_dir: Path, component: str, digest: str) -> dict[str, Any] | None:
    path = _component_cache_path(project_dir, component, digest)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("policyVersion") != PREFLIGHT_POLICY_VERSION:
        return None
    if value.get("component") != component or value.get("dependencySha256") != digest:
        return None
    payload = value.get("value")
    return dict(payload) if isinstance(payload, dict) else None


def _write_component_cache(project_dir: Path, component: str, digest: str, value: Mapping[str, Any]) -> None:
    _atomic_json(
        _component_cache_path(project_dir, component, digest),
        {
            "version": "1.0",
            "policyVersion": PREFLIGHT_POLICY_VERSION,
            "component": component,
            "dependencySha256": digest,
            "value": dict(value),
        },
    )


def _candidate_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "candidateId", "parentCandidateId", "baseArtifactSha256", "artifactSha256",
        "dependencyDigests", "recoveryClass", "strategy", "mutationSurface", "preserve",
        "changedFields", "changedScopes", "diagnosticCause", "revisionCycle",
        "assetBindings",
    )
    return {key: manifest.get(key) for key in keys}


def _update_candidate(project_dir: Path, attempt_id: str, **updates: Any) -> None:
    path = _candidate_path(project_dir, attempt_id)
    if not path.is_file():
        return
    manifest = load_convergence_candidate(project_dir, attempt_id)
    manifest.update(updates)
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(path, manifest)



def _editorial_moment_ids(edit: Mapping[str, Any]) -> list[str]:
    persian = edit.get("persian")
    moments = persian.get("moments") if isinstance(persian, Mapping) else None
    if not isinstance(moments, list):
        return []
    ids: list[str] = []
    for index, moment in enumerate(moments):
        if not isinstance(moment, Mapping):
            continue
        moment_id = str(moment.get("id") or "").strip()
        if not moment_id:
            raise PersianEditWorkspaceError(f"editorial moment {index} requires a non-empty id")
        if moment_id in ids:
            raise PersianEditWorkspaceError(f"duplicate editorial moment id: {moment_id}")
        ids.append(moment_id)
    return ids


def _editorial_baseline_path(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".drafts" / "edit" / "editorial-baseline.json"


def _validate_editorial_moment_continuity(
    project_dir: Path,
    attempt_id: str,
    edit: Mapping[str, Any],
    *,
    parent_attempt_id: str | None = None,
) -> dict[str, Any]:
    """Prevent silent beat deletion relative to the candidate's actual ancestry."""
    path = _editorial_baseline_path(project_dir)
    current = _editorial_moment_ids(edit)
    previous: list[str] = []
    if parent_attempt_id:
        previous = _editorial_moment_ids(_load_draft(project_dir, parent_attempt_id))
    elif path.is_file():
        try:
            baseline = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersianEditWorkspaceError("editorial moment baseline is unreadable") from exc
        raw_ids = baseline.get("momentIds") if isinstance(baseline, Mapping) else None
        if not isinstance(raw_ids, list) or any(not isinstance(item, str) or not item for item in raw_ids):
            raise PersianEditWorkspaceError("editorial moment baseline is invalid")
        previous = list(raw_ids)
    removed = [moment_id for moment_id in previous if moment_id not in current]
    authorization = None
    metadata = edit.get("metadata")
    if isinstance(metadata, Mapping):
        authorization = metadata.get("editorialMomentRemovalAuthorization")
    authorized = False
    if removed:
        if isinstance(authorization, Mapping):
            declared = authorization.get("removedMomentIds")
            authorized = (
                authorization.get("authorized") is True
                and authorization.get("source") == "explicit_user_response"
                and bool(str(authorization.get("decisionId") or "").strip())
                and bool(str(authorization.get("reason") or "").strip())
                and isinstance(declared, list)
                and set(str(item) for item in declared) == set(removed)
            )
        if not authorized:
            raise PersianEditWorkspaceError(
                "silent editorial moment removal is forbidden during convergence; "
                f"removed={removed}. Repair recipe/line-break/placement/timing first, or persist "
                "an explicit_user_response editorialMomentRemovalAuthorization naming exactly those ids."
            )
    # The global baseline exists for legacy/root staging. Child candidates are
    # compared to their explicit parent and must not rewrite that global baseline,
    # otherwise one sibling can make another sibling look destructively incomplete.
    if parent_attempt_id is None:
        _atomic_json(path, {
            "version": "1.0",
            "lastAttemptId": attempt_id,
            "momentIds": current,
        })
    return {
        "editorialMomentIds": current,
        "removedEditorialMomentIds": removed,
        "removalAuthorized": bool(removed and authorized),
    }

def stage_edit_draft(
    project_dir: Path,
    attempt_id: str,
    payload: Mapping[str, Any],
    *,
    parent_attempt_id: str | None = None,
    diagnostic_issue: Mapping[str, Any] | None = None,
    recovery_class: str | None = None,
    strategy: str | None = None,
    changed_fields: Sequence[str] | None = None,
    max_candidates: int = 4,
    revision_cycle: int = 0,
    hook_authority: Mapping[str, Any] | None = None,
    asset_binding_request: Mapping[str, Any] | None = None,
    enforce_asset_bindings: bool = False,
) -> dict[str, Any]:
    draft, report, canonical = _paths(project_dir, attempt_id)
    edit = extract_edit_decisions(dict(payload))
    edit = materialize_loudness_aware_mix(edit, base_dir=REPO_ROOT)
    digest = artifact_sha256(edit)
    dependency_digests = (
        _dependency_digests(edit, hook_authority=hook_authority)
        if hook_authority is not None else _dependency_digests(edit)
    )

    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or max_candidates <= 0:
        raise PersianEditWorkspaceError("max_candidates must be a positive integer")
    if not isinstance(revision_cycle, int) or isinstance(revision_cycle, bool) or revision_cycle < 0:
        raise PersianEditWorkspaceError("revision_cycle must be a non-negative integer")

    parent_id = _attempt(parent_attempt_id) if parent_attempt_id else None
    base_edit: dict[str, Any] | None = None
    base_digest: str | None = None
    if parent_id:
        parent_manifest = load_convergence_candidate(project_dir, parent_id)
        base_edit = _load_draft(project_dir, parent_id)
        base_digest = str(parent_manifest.get("artifactSha256") or artifact_sha256(base_edit))
    elif canonical.is_file():
        try:
            raw_base = json.loads(canonical.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PersianEditWorkspaceError("canonical edit artifact is unreadable") from exc
        if isinstance(raw_base, dict):
            base_edit = raw_base
            base_digest = artifact_sha256(raw_base)

    issue = dict(diagnostic_issue or {})
    if recovery_class:
        issue["recoveryClass"] = recovery_class
    plan: dict[str, Any] | None = None
    resolved_class: str | None = None
    mutation_surface: list[str] = []
    preserve: list[str] = []
    clean_changed_fields = [str(item).strip() for item in (changed_fields or []) if str(item).strip()]
    if issue or recovery_class:
        plan = recovery_policy_for_issue(issue)
        resolved_class = str(plan["recoveryClass"])
        mutation_surface = list(plan["mutationSurface"])
        preserve = list(plan["preserve"])
        if not strategy or strategy not in plan["strategies"]:
            raise PersianEditWorkspaceError(
                f"strategy {strategy!r} is not allowed for {resolved_class}; allowed={plan['strategies']}"
            )
        if not clean_changed_fields and resolved_class != "PREFLIGHT_RUNTIME":
            raise PersianEditWorkspaceError(
                f"recovery candidate {attempt_id!r} must declare changed_fields"
            )
        if "diagnostic.named_contract_field" in mutation_surface:
            # The wildcard means "the contract field this diagnostic names" -- not
            # "any field". When the diagnostic does name one, a candidate must report
            # that field rather than an unrelated one (#152). Some classes legitimately
            # carry diagnostics with no field (the strategy implies it), so this only
            # binds when a field is actually named.
            named_field = _named_contract_field(issue)
            if named_field:
                mismatched = [
                    item for item in clean_changed_fields
                    if not _field_within_named(item, named_field)
                ]
                if mismatched:
                    raise PersianEditWorkspaceError(
                        "declared changed_fields do not name the field the diagnostic reports: "
                        f"{mismatched}; diagnostic names {named_field!r}"
                    )
        else:
            undeclared = [item for item in clean_changed_fields if item not in mutation_surface]
            if undeclared:
                raise PersianEditWorkspaceError(
                    "declared changed_fields exceed the recovery mutation surface: "
                    f"{undeclared}; allowed={mutation_surface}"
                )

    changed_scopes = _changed_scopes(base_edit, edit)
    if plan is not None:
        allowed_scopes = _allowed_scopes(mutation_surface)
        forbidden = changed_scopes if "*" not in allowed_scopes else []
        if "*" not in allowed_scopes:
            forbidden = [scope for scope in changed_scopes if scope not in allowed_scopes]
        preserved_changed = [scope for scope in changed_scopes if scope in preserve]
        if "edit_digest" in preserve and base_digest is not None and base_digest != digest:
            preserved_changed.append("edit_digest")
        if forbidden or preserved_changed:
            details = sorted(set(forbidden + preserved_changed))
            raise PersianEditWorkspaceError(
                f"recovery mutation surface violation for {resolved_class}: changed scopes {details}; "
                f"allowed={mutation_surface}; preserve={preserve}"
            )

    normalized_asset_bindings: list[dict[str, Any]] = []
    asset_changed_shots = _asset_changed_shot_ids(base_edit, edit)
    binding_required = bool(
        enforce_asset_bindings
        and resolved_class == "ASSET_SELECTION"
        and (
            asset_changed_shots
            or strategy in {
                "reuse_reviewed_non_overlapping_source_window",
                "reuse_reviewed_existing_candidate",
                "use_authored_alternate_query",
            }
        )
    )
    if asset_binding_request is not None:
        try:
            normalized_asset_bindings = validate_edit_asset_bindings(
                project_dir,
                edit,
                asset_binding_request,
                required_shot_ids=asset_changed_shots,
            )
        except PersianAssetWorkspaceError as exc:
            raise PersianEditWorkspaceError(
                "asset selection recovery is not bound to reviewed asset-workspace evidence: "
                f"{exc}; send back to acquire_assets when no exact reviewed candidate exists"
            ) from exc
    elif binding_required:
        raise PersianEditWorkspaceError(
            "asset selection recovery requires exact reviewed asset-workspace bindings "
            "before edit-stage candidate consumption; send back to acquire_assets when "
            "no exact reviewed candidate exists"
        )

    geometry = geometric_hard_region_precheck(edit, repo_root=REPO_ROOT)
    geometry_blockers = geometry.get("blockingIssues")
    if isinstance(geometry_blockers, list) and geometry_blockers:
        blocker = next((dict(item) for item in geometry_blockers if isinstance(item, Mapping)), {})
        code = str(blocker.get("code") or "ASSET_SELECTION_HARD_REGION_COLLISION")
        details = blocker.get("details") if isinstance(blocker.get("details"), Mapping) else {}
        raise PersianEditWorkspaceError(
            f"[{code}] geometric precheck refused before candidate consumption; "
            f"details.stage={details.get('stage', 'geometric_precheck')}; "
            f"{blocker.get('message', 'provably infeasible reviewed hard-region geometry')}"
            + _scoped_reacquisition_hint(project_dir, edit, code, details)
        )

    diagnostic_cause = dict(issue) if issue else None
    expected_identity = {
        "candidateId": attempt_id,
        "parentCandidateId": parent_id,
        "baseArtifactSha256": base_digest,
        "artifactSha256": digest,
        "dependencyDigests": dependency_digests,
        "recoveryClass": resolved_class,
        "strategy": strategy,
        "mutationSurface": mutation_surface,
        "preserve": preserve,
        "changedFields": clean_changed_fields,
        "changedScopes": changed_scopes,
        "diagnosticCause": diagnostic_cause,
        "revisionCycle": int(revision_cycle),
        "assetBindings": normalized_asset_bindings,
    }
    candidate_path = _candidate_path(project_dir, attempt_id)
    if candidate_path.is_file():
        existing_manifest = load_convergence_candidate(project_dir, attempt_id)
        if _candidate_identity(existing_manifest) != expected_identity:
            raise PersianEditWorkspaceError(
                "attempt_id already exists with different edit bytes or recovery metadata; candidate identity is immutable"
            )
        if draft.is_file() and artifact_sha256(json.loads(draft.read_text(encoding="utf-8"))) != digest:
            raise PersianEditWorkspaceError(
                "candidate identity is immutable; staged draft bytes no longer match its manifest"
            )
        return {
            "attemptId": attempt_id,
            "candidateId": attempt_id,
            "draftPath": str(draft),
            "artifactSha256": digest,
            "candidateManifestPath": str(candidate_path),
            "idempotent": True,
            "disposition": existing_manifest.get("disposition"),
        }

    manifests = [
        item for item in _candidate_manifests(project_dir)
        if int(item.get("revisionCycle") or 0) == int(revision_cycle)
    ]
    if len(manifests) >= max_candidates:
        _write_unresolved(
            project_dir,
            reason="global_candidate_budget_exhausted",
            recovery_class=resolved_class,
            attempts_used=sum(1 for item in manifests if item.get("recoveryClass") == resolved_class),
            max_attempts=(int(plan["maxAttempts"]) if plan else None),
            global_used=len(manifests),
            global_max=max_candidates,
            diagnostic_issue=diagnostic_cause,
            revision_cycle=revision_cycle,
        )
        raise PersianEditWorkspaceError(
            f"global candidate budget exhausted: {len(manifests)} used >= {max_candidates} allowed"
        )
    if plan is not None and resolved_class:
        class_used = sum(1 for item in manifests if item.get("recoveryClass") == resolved_class)
        class_max = int(plan["maxAttempts"])
        if class_used >= class_max:
            _write_unresolved(
                project_dir,
                reason="recovery_class_candidate_budget_exhausted",
                recovery_class=resolved_class,
                attempts_used=class_used,
                max_attempts=class_max,
                global_used=len(manifests),
                global_max=max_candidates,
                diagnostic_issue=diagnostic_cause,
                revision_cycle=revision_cycle,
            )
            raise PersianEditWorkspaceError(
                f"candidate budget exhausted for {resolved_class}: {class_used} used >= {class_max} allowed"
            )

    continuity = _validate_editorial_moment_continuity(
        project_dir, attempt_id, edit, parent_attempt_id=parent_id
    )
    if draft.exists():
        existing = json.loads(draft.read_text(encoding="utf-8"))
        if artifact_sha256(existing) != digest:
            raise PersianEditWorkspaceError(
                "attempt_id already exists with different edit bytes; use a new attempt_id"
            )
    else:
        _atomic_json(draft, edit)
    if report.exists():
        old = json.loads(report.read_text(encoding="utf-8"))
        if old.get("artifactSha256") != digest:
            report.unlink()

    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "version": "1.0",
        **expected_identity,
        "producedDiagnostics": [],
        "cacheHits": {},
        "disposition": "staged",
        "createdAt": now,
        "updatedAt": now,
    }
    _atomic_json(candidate_path, manifest)
    unresolved_path = _unresolved_path(project_dir)
    if unresolved_path.is_file():
        try:
            unresolved = json.loads(unresolved_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unresolved = None
        if isinstance(unresolved, Mapping) and int(unresolved.get("revisionCycle") or 0) < revision_cycle:
            unresolved_path.unlink(missing_ok=True)
    return {
        "attemptId": attempt_id,
        "candidateId": attempt_id,
        "draftPath": str(draft),
        "artifactSha256": digest,
        "candidateManifestPath": str(candidate_path),
        "dependencyDigests": dependency_digests,
        "changedScopes": changed_scopes,
        "disposition": "staged",
        **continuity,
    }

def probe_edit_draft(
    project_dir: Path,
    attempt_id: str,
    *,
    hook_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the canonical aggregate preflight without durable workspace writes."""
    draft, _, _ = _paths(project_dir, attempt_id)
    if not draft.is_file():
        raise PersianEditWorkspaceError(f"edit draft does not exist: {draft}")
    payload = json.loads(draft.read_text(encoding="utf-8"))
    digest = artifact_sha256(payload)
    dependency_digests = (
        _dependency_digests(payload, hook_authority=hook_authority)
        if hook_authority is not None
        else _dependency_digests(payload)
    )
    aggregate_kwargs: dict[str, Any] = {"base_dir": REPO_ROOT}
    if hook_authority is not None:
        aggregate_kwargs["hook_authority"] = hook_authority
    # Browser/layout helpers may need scratch bytes, but a diagnostic probe must
    # leave no durable project state. This temporary directory is deleted before
    # return and is never candidate/cache authority.
    with TemporaryDirectory(prefix="openmontage-edit-probe-") as scratch:
        aggregate_kwargs["scratch_dir"] = Path(scratch)
        report = aggregate_preflight_edit_decisions(payload, **aggregate_kwargs)
    if report.get("artifactSha256") != digest:
        raise PersianEditWorkspaceError(
            "probe report digest does not match the staged edit bytes"
        )
    result = dict(report)
    result["attemptId"] = attempt_id
    result["draftPath"] = str(draft)
    result["dependencyDigests"] = dependency_digests
    result["readOnly"] = True
    result["durableSideEffects"] = False
    return result


def preflight_edit_draft(
    project_dir: Path, attempt_id: str, *,
    hook_authority: Mapping[str, Any] | None = None,
    recertify_promoted: bool = False,
    recertify_staged: bool = False,
) -> dict[str, Any]:
    if recertify_promoted and recertify_staged:
        raise PersianEditWorkspaceError(
            "choose only one recertification mode: promoted or staged"
        )
    draft, report_path, _ = _paths(project_dir, attempt_id)
    if not draft.is_file():
        raise PersianEditWorkspaceError(f"edit draft does not exist: {draft}")
    payload = json.loads(draft.read_text(encoding="utf-8"))
    digest = artifact_sha256(payload)
    dependency_digests = (
        _dependency_digests(payload, hook_authority=hook_authority)
        if hook_authority is not None else _dependency_digests(payload)
    )
    candidate_path = _candidate_path(project_dir, attempt_id)
    recertified = False
    if candidate_path.is_file():
        manifest = load_convergence_candidate(project_dir, attempt_id)
        staged_dependencies = manifest.get("dependencyDigests")
        if staged_dependencies and staged_dependencies != dependency_digests:
            if not (recertify_promoted or recertify_staged):
                raise PersianEditWorkspaceError(
                    "refusing preflight: staged dependency context changed after candidate creation"
                )
            manifest_digest = str(manifest.get("artifactSha256") or "")
            if manifest_digest != digest:
                raise PersianEditWorkspaceError(
                    "candidate recertification requires the same immutable edit digest"
                )
            if recertify_promoted:
                if manifest.get("disposition") != "promoted":
                    raise PersianEditWorkspaceError(
                        "promoted candidate recertification requires the candidate to already be promoted"
                    )
                canonical = project_dir.expanduser().resolve() / "artifacts" / "edit_decisions.json"
                if not canonical.is_file():
                    raise PersianEditWorkspaceError(
                        "promoted candidate recertification requires the canonical edit artifact"
                    )
                canonical_payload = json.loads(canonical.read_text(encoding="utf-8"))
                canonical_digest = artifact_sha256(canonical_payload)
                if canonical_digest != digest:
                    raise PersianEditWorkspaceError(
                        "promoted candidate recertification requires the same canonical edit digest"
                    )
            else:
                disposition = str(manifest.get("disposition") or "")
                if disposition == "promoted":
                    raise PersianEditWorkspaceError(
                        "staged candidate recertification cannot rewrite promoted certification; "
                        "use promoted recertification"
                    )
                if disposition not in {"staged", "blocked", "preflight_passed"}:
                    raise PersianEditWorkspaceError(
                        "staged candidate recertification requires a staged, blocked, or "
                        "preflight-passed immutable candidate"
                    )

            old_report_sha = str(manifest.get("preflightReportSha256") or "")
            old_report = None
            if report_path.is_file():
                report_bytes = report_path.read_bytes()
                actual_old_report_sha = hashlib.sha256(report_bytes).hexdigest()
                if old_report_sha and actual_old_report_sha != old_report_sha:
                    raise PersianEditWorkspaceError(
                        "refusing recertification: prior preflight report changed after certification"
                    )
                old_report_sha = actual_old_report_sha
                old_report = json.loads(report_bytes.decode("utf-8"))

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            history_path = (
                project_dir.expanduser().resolve()
                / ".history"
                / "preflight_recertifications"
                / _attempt(attempt_id)
                / f"{stamp}.json"
            )
            history_record = {
                "version": "1.0",
                "candidateId": attempt_id,
                "archivedAt": datetime.now(timezone.utc).isoformat(),
                "reason": "policy_or_implementation_dependency_change",
                "artifactSha256": digest,
                "dependencyDigests": dict(staged_dependencies or {}),
                "preflightReportSha256": old_report_sha or None,
                "candidateManifest": manifest,
                "preflightReport": old_report,
            }
            _atomic_json(history_path, history_record)
            history = list(manifest.get("certificationHistory") or [])
            history.append({
                "path": str(history_path),
                "at": history_record["archivedAt"],
                "reason": history_record["reason"],
                "dependencyDigests": dict(staged_dependencies or {}),
                "preflightReportSha256": old_report_sha or None,
            })
            _update_candidate(
                project_dir,
                attempt_id,
                dependencyDigests=dependency_digests,
                certificationHistory=history,
                disposition="staged",
                recertificationReason=history_record["reason"],
            )
            recertified = True
    elif recertify_promoted or recertify_staged:
        mode = "promoted" if recertify_promoted else "staged"
        raise PersianEditWorkspaceError(
            f"{mode} candidate recertification requires an existing candidate"
        )
    cache_path = _cache_path(project_dir, digest)

    cached: dict[str, Any] | None = None
    if cache_path.is_file():
        try:
            candidate = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            candidate = None
        if _valid_cached_report(
            candidate, digest=digest, dependency_digests=dependency_digests
        ):
            cached = dict(candidate)

    if cached is None:
        key_map = {
            "retention": "retentionAudit",
            "hook": "hookQualityAudit",
            "browser": "browserEvidence",
        }
        precomputed: dict[str, Any] = {}
        component_hits: dict[str, bool] = {}
        for component, report_key in key_map.items():
            value = _load_component_cache(
                project_dir, component, dependency_digests[component]
            )
            component_hits[component] = value is not None
            if value is not None:
                precomputed[report_key] = value

        aggregate_kwargs = {
            "base_dir": REPO_ROOT,
            "precomputed_components": precomputed,
            "scratch_dir": workspace_directory(project_dir, "probes"),
        }
        if hook_authority is not None:
            aggregate_kwargs["hook_authority"] = hook_authority
        computed = aggregate_preflight_edit_decisions(payload, **aggregate_kwargs)
        if computed.get("artifactSha256") != digest:
            raise PersianEditWorkspaceError(
                "preflight report digest does not match the staged edit bytes"
            )
        computed["cacheHit"] = False
        computed["cacheKey"] = digest
        computed["componentCacheHits"] = component_hits
        computed["dependencyDigests"] = dependency_digests

        evidence = computed.get("evidence") if isinstance(computed.get("evidence"), Mapping) else {}
        component_values = {
            "retention": evidence.get("retentionAudit"),
            "hook": evidence.get("hookQualityAudit"),
            "browser": evidence.get("browserEvidence"),
        }
        for component, value in component_values.items():
            if not component_hits[component] and isinstance(value, Mapping):
                _write_component_cache(
                    project_dir,
                    component,
                    dependency_digests[component],
                    value,
                )
        _atomic_json(cache_path, computed)
        report = dict(computed)
    else:
        report = cached
        report["cacheHit"] = True
        report["cacheKey"] = digest
        # The whole report cache short-circuited component lookup. Do not claim
        # component-level hits that did not actually occur.
        report["componentCacheHits"] = {
            "retention": False,
            "hook": False,
            "browser": False,
        }
        report["dependencyDigests"] = dependency_digests

    report["attemptId"] = attempt_id
    report["draftPath"] = str(draft)
    if recertified:
        if recertify_promoted:
            report["recertifiedPromotedCandidate"] = True
        if recertify_staged:
            report["recertifiedStagedCandidate"] = True
    _atomic_json(report_path, report)
    report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    _update_candidate(
        project_dir,
        attempt_id,
        dependencyDigests=dependency_digests,
        producedDiagnostics=list(report.get("blockingIssues") or []),
        cacheHits={
            "fullReport": bool(report.get("cacheHit")),
            **dict(report.get("componentCacheHits") or {}),
        },
        disposition="preflight_passed" if report.get("ok") is True else "blocked",
        preflightReportSha256=report_sha,
        preflightArtifactSha256=digest,
    )
    return report

def load_promotable_edit_draft(
    project_dir: Path, attempt_id: str, *, hook_authority: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Load the exact passing draft/report pair without mutating canonical state."""
    draft, report_path, _ = _paths(project_dir, attempt_id)
    if not draft.is_file() or not report_path.is_file():
        raise PersianEditWorkspaceError(
            "promotion requires both the staged draft and its persisted preflight report"
        )
    edit = json.loads(draft.read_text(encoding="utf-8"))
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes.decode("utf-8"))
    digest = artifact_sha256(edit)
    candidate_path = _candidate_path(project_dir, attempt_id)
    if candidate_path.is_file():
        manifest = load_convergence_candidate(project_dir, attempt_id)
        expected_report_sha = str(manifest.get("preflightReportSha256") or "")
        actual_report_sha = hashlib.sha256(report_bytes).hexdigest()
        if expected_report_sha and actual_report_sha != expected_report_sha:
            raise PersianEditWorkspaceError(
                "refusing promotion: preflight report changed after candidate preflight"
            )
        expected_artifact_sha = str(manifest.get("preflightArtifactSha256") or "")
        if expected_artifact_sha and expected_artifact_sha != digest:
            raise PersianEditWorkspaceError(
                "refusing promotion: candidate manifest preflight digest differs from staged draft"
            )
    expected_dependencies = (
        _dependency_digests(edit, hook_authority=hook_authority)
        if hook_authority is not None else _dependency_digests(edit)
    )
    reported_dependencies = report.get("dependencyDigests")
    if hook_authority is not None and reported_dependencies != expected_dependencies:
        raise PersianEditWorkspaceError(
            "refusing promotion: preflight dependency context changed after review"
        )
    if report.get("ok") is not True:
        raise PersianEditWorkspaceError("refusing promotion: preflight report did not pass")
    if report.get("artifactSha256") != digest:
        raise PersianEditWorkspaceError(
            "refusing promotion: draft digest differs from the passing preflight report"
        )
    return edit, report, digest


def promote_edit_draft(
    project_dir: Path, attempt_id: str, *, hook_authority: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    draft, _, canonical = _paths(project_dir, attempt_id)
    edit, _, digest = load_promotable_edit_draft(
        project_dir, attempt_id, hook_authority=hook_authority
    )
    candidate_manifest = load_convergence_candidate(project_dir, attempt_id)
    asset_bindings = candidate_manifest.get("assetBindings")
    if isinstance(asset_bindings, list) and asset_bindings:
        asset_manifest_path = project_dir.expanduser().resolve() / "artifacts" / "asset_manifest.json"
        if not asset_manifest_path.is_file():
            raise PersianEditWorkspaceError(
                "refusing promotion: edit-bound asset recovery requires canonical asset_manifest rebinding"
            )
        try:
            asset_manifest = json.loads(asset_manifest_path.read_text(encoding="utf-8"))
            if not isinstance(asset_manifest, Mapping):
                raise PersianAssetWorkspaceError("canonical asset_manifest must be an object")
            validate_edit_asset_bindings_against_manifest(
                project_dir, asset_bindings, asset_manifest
            )
        except (OSError, json.JSONDecodeError, PersianAssetWorkspaceError) as exc:
            raise PersianEditWorkspaceError(
                "refusing promotion: canonical asset_manifest does not match edit-bound "
                f"reviewed asset identity: {exc}"
            ) from exc

    canonical.parent.mkdir(parents=True, exist_ok=True)
    if canonical.exists():
        current = json.loads(canonical.read_text(encoding="utf-8"))
        current_digest = artifact_sha256(current)
        if current_digest == digest:
            _update_candidate(
                project_dir, attempt_id, disposition="promoted",
                promotedAt=datetime.now(timezone.utc).isoformat(),
            )
            _atomic_json(_editorial_baseline_path(project_dir), {
                "version": "1.0",
                "lastAttemptId": attempt_id,
                "momentIds": _editorial_moment_ids(edit),
            })
            _unresolved_path(project_dir).unlink(missing_ok=True)
            return {
                "promoted": False,
                "idempotent": True,
                "canonicalPath": str(canonical),
                "artifactSha256": digest,
            }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        history = (
            project_dir.resolve()
            / ".history"
            / "edit_decisions"
            / f"{stamp}-{current_digest[:12]}.json"
        )
        history.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(canonical, history)

    temp = canonical.with_suffix(canonical.suffix + ".tmp")
    temp.write_bytes(draft.read_bytes())
    temp.replace(canonical)
    _update_candidate(
        project_dir, attempt_id, disposition="promoted",
        promotedAt=datetime.now(timezone.utc).isoformat(),
    )
    _atomic_json(_editorial_baseline_path(project_dir), {
        "version": "1.0",
        "lastAttemptId": attempt_id,
        "momentIds": _editorial_moment_ids(edit),
    })
    _unresolved_path(project_dir).unlink(missing_ok=True)
    return {
        "promoted": True,
        "idempotent": False,
        "canonicalPath": str(canonical),
        "artifactSha256": digest,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PersianEditWorkspaceError("edit input must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persian-edit-workspace")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage")
    stage.add_argument("project_dir", type=Path)
    stage.add_argument("attempt_id")
    stage.add_argument("input", type=Path)
    probe = sub.add_parser("preflight")
    probe.add_argument("project_dir", type=Path)
    probe.add_argument("attempt_id")
    promote = sub.add_parser("promote")
    promote.add_argument("project_dir", type=Path)
    promote.add_argument("attempt_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            result = stage_edit_draft(
                args.project_dir, args.attempt_id, _read_json(args.input)
            )
        elif args.command == "preflight":
            result = preflight_edit_draft(args.project_dir, args.attempt_id)
        else:
            result = promote_edit_draft(args.project_dir, args.attempt_id)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
