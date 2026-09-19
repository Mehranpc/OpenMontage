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
from typing import Any, Mapping, Sequence

from lib.paths import REPO_ROOT
from lib.persian_audio_policy import materialize_loudness_aware_mix
from lib.persian_preflight import (
    PREFLIGHT_POLICY_VERSION, aggregate_preflight_edit_decisions, extract_edit_decisions,
)
from lib.persian_recovery_policy import recovery_policy_for_issue

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


def _valid_cached_report(value: object, *, digest: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("artifactSha256") == digest
        and value.get("policyVersion") == PREFLIGHT_POLICY_VERSION
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
                key: raw.get(key)
                for key in (
                    "id", "kind", "startSeconds", "endSeconds", "segments",
                    "userAuthoredShortHook",
                )
                if key in raw
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


def _dependency_digests(edit: Mapping[str, Any]) -> dict[str, str]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    payloads = {
        "retention": {"version": "retention-v1", "deps": _retention_dependency_payload(edit)},
        "hook": {"version": "hook-v1", "deps": _hook_dependency_payload(edit)},
        "browser": {"version": "browser-v1", "deps": persian},
    }
    return {
        name: _stable_digest({"policyVersion": PREFLIGHT_POLICY_VERSION, **payload})
        for name, payload in payloads.items()
    }


def _copy_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    moments = []
    for raw in persian.get("moments") or []:
        if isinstance(raw, Mapping):
            moments.append({
                "id": raw.get("id"),
                "segments": raw.get("segments"),
            })
    captions = []
    for raw in persian.get("captions") or []:
        if isinstance(raw, Mapping):
            captions.append({"id": raw.get("id"), "text": raw.get("text")})
    beats = []
    for raw in persian.get("typographicBeats") or []:
        if isinstance(raw, Mapping):
            beats.append({"id": raw.get("id"), "text": raw.get("text"), "segments": raw.get("segments")})
    return {"moments": moments, "captions": captions, "typographicBeats": beats}


def _typography_payload(edit: Mapping[str, Any]) -> list[dict[str, Any]]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    result: list[dict[str, Any]] = []
    ignored = {"id", "kind", "startSeconds", "endSeconds", "segments"}
    for raw in persian.get("moments") or []:
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
        if style:
            result.append({"id": raw.get("id"), **style})
    return result


def _asset_payload(edit: Mapping[str, Any]) -> list[dict[str, Any]]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    result: list[dict[str, Any]] = []
    tokens = ("src", "source", "asset", "provider", "clip", "query", "crop", "window", "media", "path", "url", "video")
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


def _scene_payload(edit: Mapping[str, Any]) -> list[dict[str, Any]]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    result: list[dict[str, Any]] = []
    keys = {
        "id", "visualEventId", "changeType", "narrativeRole", "humanPresence",
        "semanticRole", "semanticDirection", "selectionReason", "openingSemanticMatch",
    }
    for raw in persian.get("shots") or []:
        if isinstance(raw, Mapping):
            result.append({key: raw.get(key) for key in sorted(keys) if key in raw})
    return result


def _timeline_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    keys = {"id", "kind", "startSeconds", "endSeconds"}
    return {
        "durationSeconds": persian.get("durationSeconds"),
        "shots": _shot_subset(persian.get("shots"), {"id", "startSeconds", "endSeconds"}),
        "moments": _moment_subset(persian.get("moments"), keys),
        "typographicBeats": _moment_subset(persian.get("typographicBeats"), keys),
        "captions": _moment_subset(persian.get("captions"), {"id", "startSeconds", "endSeconds"}),
    }


def _hook_scope_payload(edit: Mapping[str, Any]) -> dict[str, Any]:
    return _hook_dependency_payload(edit)


def _scope_digests(edit: Mapping[str, Any]) -> dict[str, str]:
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    scope_payloads: dict[str, Any] = {
        "hook": _hook_scope_payload(edit),
        "captions": persian.get("captions") or [],
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
    }
    return {name: _stable_digest(value) for name, value in scope_payloads.items()}


def _changed_scopes(base_edit: Mapping[str, Any] | None, edit: Mapping[str, Any]) -> list[str]:
    if base_edit is None:
        return []
    before = _scope_digests(base_edit)
    after = _scope_digests(edit)
    return sorted(name for name in after if before.get(name) != after.get(name))


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


def convergence_status(project_dir: Path) -> dict[str, Any]:
    manifests = _candidate_manifests(project_dir)
    unresolved = None
    path = _unresolved_path(project_dir)
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, dict):
            unresolved = value
    promoted = [item for item in manifests if item.get("disposition") == "promoted"]
    return {
        "version": "1.0",
        "status": "needs_revision" if unresolved else "active",
        "candidateCount": len(manifests),
        "candidateIds": [str(item.get("candidateId")) for item in manifests],
        "promotedCandidateId": str(promoted[-1].get("candidateId")) if promoted else None,
        "unresolved": unresolved,
    }


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
    project_dir: Path, attempt_id: str, edit: Mapping[str, Any]
) -> dict[str, Any]:
    """Prevent preflight convergence from deleting authored editorial beats silently."""
    path = _editorial_baseline_path(project_dir)
    current = _editorial_moment_ids(edit)
    previous: list[str] = []
    if path.is_file():
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
    project_dir: Path, attempt_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    draft, report, _ = _paths(project_dir, attempt_id)
    edit = extract_edit_decisions(dict(payload))
    # The mix becomes part of the candidate bytes before digesting. The render does
    # not make an independent late mix decision, so preflight and promotion remain
    # digest-bound to the exact speech-time gain that will execute.
    edit = materialize_loudness_aware_mix(edit, base_dir=REPO_ROOT)
    continuity = _validate_editorial_moment_continuity(project_dir, attempt_id, edit)
    digest = artifact_sha256(edit)
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
    return {
        "attemptId": attempt_id,
        "draftPath": str(draft),
        "artifactSha256": digest,
        **continuity,
    }


def preflight_edit_draft(project_dir: Path, attempt_id: str) -> dict[str, Any]:
    draft, report_path, _ = _paths(project_dir, attempt_id)
    if not draft.is_file():
        raise PersianEditWorkspaceError(f"edit draft does not exist: {draft}")
    payload = json.loads(draft.read_text(encoding="utf-8"))
    digest = artifact_sha256(payload)
    cache_path = _cache_path(project_dir, digest)

    cached: dict[str, Any] | None = None
    if cache_path.is_file():
        try:
            candidate = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            candidate = None
        if _valid_cached_report(candidate, digest=digest):
            cached = dict(candidate)

    if cached is None:
        computed = aggregate_preflight_edit_decisions(payload, base_dir=REPO_ROOT)
        if computed.get("artifactSha256") != digest:
            raise PersianEditWorkspaceError(
                "preflight report digest does not match the staged edit bytes"
            )
        computed["cacheHit"] = False
        computed["cacheKey"] = digest
        _atomic_json(cache_path, computed)
        report = dict(computed)
    else:
        report = cached
        report["cacheHit"] = True
        report["cacheKey"] = digest

    report["attemptId"] = attempt_id
    report["draftPath"] = str(draft)
    _atomic_json(report_path, report)
    return report


def load_promotable_edit_draft(
    project_dir: Path, attempt_id: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Load the exact passing draft/report pair without mutating canonical state."""
    draft, report_path, _ = _paths(project_dir, attempt_id)
    if not draft.is_file() or not report_path.is_file():
        raise PersianEditWorkspaceError(
            "promotion requires both the staged draft and its persisted preflight report"
        )
    edit = json.loads(draft.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    digest = artifact_sha256(edit)
    if report.get("ok") is not True:
        raise PersianEditWorkspaceError("refusing promotion: preflight report did not pass")
    if report.get("artifactSha256") != digest:
        raise PersianEditWorkspaceError(
            "refusing promotion: draft digest differs from the passing preflight report"
        )
    return edit, report, digest


def promote_edit_draft(project_dir: Path, attempt_id: str) -> dict[str, Any]:
    draft, _, canonical = _paths(project_dir, attempt_id)
    edit, _, digest = load_promotable_edit_draft(project_dir, attempt_id)

    canonical.parent.mkdir(parents=True, exist_ok=True)
    if canonical.exists():
        current = json.loads(canonical.read_text(encoding="utf-8"))
        current_digest = artifact_sha256(current)
        if current_digest == digest:
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
