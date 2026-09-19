"""Durable asset candidate review/selection workspace for Persian production.

Discovery/download remains owned by ``direct_clip_search``.  This module persists the
editorial state that starts after bytes exist: source/window/crop identity, review
evidence, rejection taxonomy, duplicate-window safety, alternate reuse, and selection.
The canonical ``asset_manifest`` remains the selected output artifact; this workspace is
history and reusable evidence, not a second manifest authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

_PROVIDER_ALIASES = {
    "pexels": "pexels",
    "pixabay": "pixabay_video",
    "pixabay_video": "pixabay_video",
}
_REJECTION_CATEGORIES = {"technical", "semantic", "editorial"}
_STAGED_STOCK_RISKS = {"low", "medium", "high"}
_RESOLUTION_QUALITIES = {"strong", "acceptable", "weak"}
_EPSILON = 1e-9


class PersianAssetWorkspaceError(ValueError):
    pass


def _root(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".asset-workspace"


def _discovery_root(project_dir: Path) -> Path:
    return _root(project_dir) / "discovery"


def _discovery_candidate_path(project_dir: Path, discovery_id: str) -> Path:
    return _discovery_root(project_dir) / "candidates" / f"{discovery_id}.json"


def _pass_path(project_dir: Path, retry_pass: int) -> Path:
    return _discovery_root(project_dir) / "passes" / f"pass-{retry_pass:03d}.json"


def _candidate_path(project_dir: Path, candidate_id: str) -> Path:
    return _root(project_dir) / "candidates" / f"{candidate_id}.json"


def _selections_path(project_dir: Path) -> Path:
    return _root(project_dir) / "selections.json"


def _stable_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_stable_bytes(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PersianAssetWorkspaceError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianAssetWorkspaceError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PersianAssetWorkspaceError(f"{label} must be a JSON object")
    return value


def _provider(raw: object) -> str:
    value = str(raw or "").strip().lower()
    normalized = _PROVIDER_ALIASES.get(value)
    if not normalized:
        raise PersianAssetWorkspaceError(f"unsupported or missing asset provider: {value!r}")
    return normalized


def _source_id(clip: Mapping[str, Any]) -> str:
    value = str(clip.get("source_id") or clip.get("clip_id") or "").strip()
    if not value:
        raise PersianAssetWorkspaceError("discovered asset requires source_id or clip_id")
    return value


def _project_path(project_dir: Path, raw: object) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise PersianAssetWorkspaceError("discovered asset requires a local path")
    root = project_dir.expanduser().resolve()
    path = Path(value).expanduser()
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PersianAssetWorkspaceError(f"asset path must stay inside its project: {path}") from exc
    if not path.is_file():
        raise PersianAssetWorkspaceError(f"discovered asset file does not exist: {path}")
    return path


def _number(value: object, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise PersianAssetWorkspaceError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PersianAssetWorkspaceError(f"{field} must be numeric") from exc
    if minimum is not None and result < minimum:
        raise PersianAssetWorkspaceError(f"{field} must be >= {minimum}")
    return result


def _normalize_crop(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not str(raw.get("mode") or "").strip():
        raise PersianAssetWorkspaceError("intended_crop requires a non-empty mode")
    crop: dict[str, Any] = {str(key): value for key, value in raw.items()}
    for key in ("x", "y", "w", "h"):
        if key not in crop:
            continue
        value = _number(crop[key], field=f"intended_crop.{key}")
        if value < 0 or value > 1:
            raise PersianAssetWorkspaceError(f"intended_crop.{key} must be between 0 and 1")
        crop[key] = round(value, 6)
    if "w" in crop and crop["w"] <= 0:
        raise PersianAssetWorkspaceError("intended_crop.w must be positive")
    if "h" in crop and crop["h"] <= 0:
        raise PersianAssetWorkspaceError("intended_crop.h must be positive")
    if "x" in crop and "w" in crop and crop["x"] + crop["w"] > 1 + _EPSILON:
        raise PersianAssetWorkspaceError("intended_crop exceeds horizontal source bounds")
    if "y" in crop and "h" in crop and crop["y"] + crop["h"] > 1 + _EPSILON:
        raise PersianAssetWorkspaceError("intended_crop exceeds vertical source bounds")
    return crop


def _discovery_id(provider: str, source_id: str) -> str:
    return f"asset-source-{_sha256({'provider': provider, 'sourceId': source_id})[:20]}"


def _candidate_id(identity: Mapping[str, Any]) -> str:
    return f"asset-{_sha256(identity)[:24]}"


def record_discovery_pass(
    project_dir: Path,
    retry_pass: int,
    clips: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist one acquisition pass without turning discovery into selection truth."""
    if not isinstance(retry_pass, int) or isinstance(retry_pass, bool) or retry_pass < 0:
        raise PersianAssetWorkspaceError("retry_pass must be a non-negative integer")
    if not isinstance(clips, Sequence) or isinstance(clips, (str, bytes)):
        raise PersianAssetWorkspaceError("clips must be a sequence of discovered clip objects")

    candidate_ids: list[str] = []
    records: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for raw in clips:
        if not isinstance(raw, Mapping):
            raise PersianAssetWorkspaceError("discovered clip entries must be objects")
        provider = _provider(raw.get("source") or raw.get("provider"))
        source_id = _source_id(raw)
        path = _project_path(project_dir, raw.get("path"))
        if str(raw.get("kind") or "video").strip().lower() != "video":
            raise PersianAssetWorkspaceError("Persian asset workspace accepts video candidates only")
        duration = _number(raw.get("duration", raw.get("duration_seconds", 0.0)), field="duration", minimum=0.0)
        discovery_id = _discovery_id(provider, source_id)
        record = {
            "version": "1.0",
            "discoveryId": discovery_id,
            "identity": {"provider": provider, "sourceId": source_id},
            "clipId": str(raw.get("clip_id") or ""),
            "originalUrl": str(raw.get("source_url") or raw.get("original_url") or ""),
            "query": str(raw.get("query") or ""),
            "slotId": str(raw.get("slot_id") or ""),
            "kind": "video",
            "path": str(path),
            "durationSeconds": duration,
            "width": int(raw.get("width") or 0),
            "height": int(raw.get("height") or 0),
            "creator": str(raw.get("creator") or ""),
            "license": raw.get("license"),
            "sourceTags": list(raw.get("source_tags") or []),
            "firstSeenPass": retry_pass,
            "updatedAt": now,
        }
        path_out = _discovery_candidate_path(project_dir, discovery_id)
        if path_out.is_file():
            existing = _read_object(path_out, label="discovery candidate")
            immutable = (existing.get("identity"), existing.get("kind"))
            if immutable != (record["identity"], "video"):
                raise PersianAssetWorkspaceError("discovery candidate identity is immutable")
            record["firstSeenPass"] = int(existing.get("firstSeenPass") or retry_pass)
        _atomic_json(path_out, record)
        candidate_ids.append(discovery_id)
        records.append(record)

    pass_record = {
        "version": "1.0",
        "retryPass": retry_pass,
        "candidateIds": candidate_ids,
        "candidateCount": len(candidate_ids),
        "recordedAt": now,
    }
    path = _pass_path(project_dir, retry_pass)
    if path.is_file():
        existing = _read_object(path, label="asset discovery pass")
        if existing.get("candidateIds") != candidate_ids:
            raise PersianAssetWorkspaceError(
                "asset discovery pass identity is immutable; use the next retry pass"
            )
        return {**existing, "idempotent": True}
    _atomic_json(path, pass_record)
    return {**pass_record, "idempotent": False}


def _load_discovery(project_dir: Path, discovery_id: str) -> dict[str, Any]:
    return _read_object(
        _discovery_candidate_path(project_dir, str(discovery_id)),
        label="discovery candidate",
    )


def stage_asset_candidate(
    project_dir: Path,
    *,
    discovery_id: str,
    visual_event_id: str,
    semantic_beat_id: str,
    source_in_seconds: float,
    duration_seconds: float,
    intended_crop: Mapping[str, Any],
    candidate_rank: int,
    query: str,
    narration_span: str,
    narrative_role: str | None = None,
) -> dict[str, Any]:
    discovery = _load_discovery(project_dir, discovery_id)
    event_id = str(visual_event_id or "").strip()
    beat_id = str(semantic_beat_id or "").strip()
    if not event_id or not beat_id:
        raise PersianAssetWorkspaceError("candidate requires visual_event_id and semantic_beat_id")
    if isinstance(candidate_rank, bool) or not isinstance(candidate_rank, int) or candidate_rank < 1:
        raise PersianAssetWorkspaceError("candidate_rank must be an integer >= 1")
    start = _number(source_in_seconds, field="source_in_seconds", minimum=0.0)
    duration = _number(duration_seconds, field="duration_seconds")
    if duration <= 0:
        raise PersianAssetWorkspaceError("duration_seconds must be positive")
    end = start + duration
    source_duration = float(discovery.get("durationSeconds") or 0.0)
    if source_duration > 0 and end > source_duration + _EPSILON:
        raise PersianAssetWorkspaceError(
            f"selected source window ends at {end:.3f}s beyond source duration {source_duration:.3f}s"
        )
    crop = _normalize_crop(intended_crop)
    identity = {
        "provider": discovery["identity"]["provider"],
        "sourceId": discovery["identity"]["sourceId"],
        "sourceWindow": {
            "startSeconds": round(start, 6),
            "endSeconds": round(end, 6),
        },
        "intendedCrop": crop,
    }
    candidate_id = _candidate_id(identity)
    now = datetime.now(timezone.utc).isoformat()
    context = {
        "visualEventId": event_id,
        "semanticBeatId": beat_id,
        "narrativeRole": str(narrative_role or ""),
        "query": str(query or "").strip(),
        "candidateRank": candidate_rank,
        "narrationSpan": str(narration_span or "").strip(),
    }
    if not context["query"] or not context["narrationSpan"]:
        raise PersianAssetWorkspaceError("candidate requires query and narration_span")
    path = _candidate_path(project_dir, candidate_id)
    if path.is_file():
        existing = _read_object(path, label="asset candidate")
        if existing.get("identity") != identity or existing.get("context") != context:
            raise PersianAssetWorkspaceError(
                "asset candidate identity/context is immutable; stage a distinct source window/crop"
            )
        return {
            "candidateId": candidate_id,
            "identitySha256": str(existing.get("identitySha256") or _sha256(identity)),
            "idempotent": True,
            "disposition": existing.get("disposition"),
        }
    record = {
        "version": "1.0",
        "candidateId": candidate_id,
        "discoveryId": discovery_id,
        "identity": identity,
        "identitySha256": _sha256(identity),
        "context": context,
        "source": {
            "path": discovery["path"],
            "durationSeconds": discovery.get("durationSeconds"),
            "width": discovery.get("width"),
            "height": discovery.get("height"),
            "originalUrl": discovery.get("originalUrl"),
            "creator": discovery.get("creator"),
            "license": discovery.get("license"),
            "sourceTags": discovery.get("sourceTags") or [],
        },
        "review": None,
        "reviewSha256": None,
        "rejection": None,
        "disposition": "staged",
        "createdAt": now,
        "updatedAt": now,
    }
    _atomic_json(path, record)
    return {
        "candidateId": candidate_id,
        "identitySha256": record["identitySha256"],
        "idempotent": False,
        "disposition": "staged",
    }


def load_asset_candidate(project_dir: Path, candidate_id: str) -> dict[str, Any]:
    return _read_object(_candidate_path(project_dir, str(candidate_id)), label="asset candidate")


def _candidate_records(project_dir: Path) -> list[dict[str, Any]]:
    root = _root(project_dir) / "candidates"
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("asset-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _validate_review(review: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(review, Mapping):
        raise PersianAssetWorkspaceError("candidate review must be an object")
    result = {str(key): value for key, value in review.items()}
    frame = result.get("frame_review")
    if not isinstance(frame, Mapping):
        raise PersianAssetWorkspaceError("candidate review requires frame_review")
    for key in ("start", "middle", "end"):
        if frame.get(key) is not True:
            raise PersianAssetWorkspaceError(f"frame_review.{key} must be true")
    if not str(frame.get("observed") or "").strip():
        raise PersianAssetWorkspaceError("frame_review.observed must be non-empty")
    for field in ("shows_subject", "human_presence", "affect_match"):
        if not isinstance(result.get(field), bool):
            raise PersianAssetWorkspaceError(f"{field} must be boolean")
    risk = str(result.get("staged_stock_risk") or "").strip().lower()
    if risk not in _STAGED_STOCK_RISKS:
        raise PersianAssetWorkspaceError("staged_stock_risk must be low, medium, or high")
    result["staged_stock_risk"] = risk
    for field in ("relevance_reason", "selection_reason"):
        if not str(result.get(field) or "").strip():
            raise PersianAssetWorkspaceError(f"{field} must be non-empty")
    geometry = result.get("geometry_review")
    if not isinstance(geometry, Mapping):
        raise PersianAssetWorkspaceError("candidate review requires geometry_review")
    if not isinstance(geometry.get("crop_safe"), bool):
        raise PersianAssetWorkspaceError("geometry_review.crop_safe must be boolean")
    if not str(geometry.get("observed") or "").strip():
        raise PersianAssetWorkspaceError("geometry_review.observed must be non-empty")
    resolution = str(result.get("resolution_quality") or "acceptable").strip().lower()
    if resolution not in _RESOLUTION_QUALITIES:
        raise PersianAssetWorkspaceError(
            "resolution_quality must be strong, acceptable, or weak"
        )
    result["resolution_quality"] = resolution
    return result


def record_candidate_review(
    project_dir: Path, candidate_id: str, review: Mapping[str, Any]
) -> dict[str, Any]:
    candidate = load_asset_candidate(project_dir, candidate_id)
    normalized = _validate_review(review)
    review_sha = _sha256({
        "candidateIdentitySha256": candidate["identitySha256"],
        "candidateContext": candidate.get("context") or {},
        "review": normalized,
    })
    existing_sha = str(candidate.get("reviewSha256") or "")
    if existing_sha:
        if existing_sha != review_sha:
            raise PersianAssetWorkspaceError(
                "candidate review evidence is immutable for an unchanged candidate identity"
            )
        return {
            "candidateId": candidate_id,
            "reviewSha256": existing_sha,
            "idempotent": True,
            "disposition": candidate.get("disposition"),
        }
    candidate["review"] = normalized
    candidate["reviewSha256"] = review_sha
    candidate["disposition"] = "reviewed"
    candidate["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(_candidate_path(project_dir, candidate_id), candidate)
    return {
        "candidateId": candidate_id,
        "reviewSha256": review_sha,
        "idempotent": False,
        "disposition": "reviewed",
    }


def reject_asset_candidate(
    project_dir: Path,
    candidate_id: str,
    *,
    category: str,
    reason: str,
) -> dict[str, Any]:
    candidate = load_asset_candidate(project_dir, candidate_id)
    normalized_category = str(category or "").strip().lower()
    if normalized_category not in _REJECTION_CATEGORIES:
        raise PersianAssetWorkspaceError(
            "rejection category must be technical, semantic, or editorial"
        )
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise PersianAssetWorkspaceError("candidate rejection requires a reason")
    selections = _read_selections(project_dir)
    if any(item.get("candidateId") == candidate_id for item in selections.values()):
        raise PersianAssetWorkspaceError("selected candidate must be replaced before rejection")
    candidate["rejection"] = {
        "category": normalized_category,
        "reason": clean_reason,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    candidate["disposition"] = "rejected"
    candidate["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(_candidate_path(project_dir, candidate_id), candidate)
    return candidate


def reusable_asset_candidates(
    project_dir: Path, *, visual_event_id: str
) -> list[dict[str, Any]]:
    event_id = str(visual_event_id or "").strip()
    result: list[dict[str, Any]] = []
    for candidate in _candidate_records(project_dir):
        if str((candidate.get("context") or {}).get("visualEventId") or "") != event_id:
            continue
        if not candidate.get("reviewSha256") or candidate.get("disposition") == "rejected":
            continue
        result.append({
            "candidateId": candidate["candidateId"],
            "reviewSha256": candidate["reviewSha256"],
            "candidateRank": int((candidate.get("context") or {}).get("candidateRank") or 999999),
            "disposition": candidate.get("disposition"),
            "identity": candidate.get("identity"),
        })
    result.sort(key=lambda item: (item["candidateRank"], item["candidateId"]))
    return result


def _read_selections(project_dir: Path) -> dict[str, dict[str, Any]]:
    path = _selections_path(project_dir)
    if not path.is_file():
        return {}
    value = _read_object(path, label="asset selections")
    selections = value.get("selections")
    if not isinstance(selections, dict):
        raise PersianAssetWorkspaceError("asset selections file is invalid")
    return {
        str(key): dict(item)
        for key, item in selections.items()
        if isinstance(item, Mapping)
    }


def _write_selections(project_dir: Path, selections: Mapping[str, Mapping[str, Any]]) -> None:
    _atomic_json(
        _selections_path(project_dir),
        {
            "version": "1.0",
            "selections": {str(key): dict(value) for key, value in selections.items()},
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
    )


def _windows_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_window = left.get("sourceWindow") or {}
    right_window = right.get("sourceWindow") or {}
    start = max(float(left_window.get("startSeconds") or 0.0), float(right_window.get("startSeconds") or 0.0))
    end = min(float(left_window.get("endSeconds") or 0.0), float(right_window.get("endSeconds") or 0.0))
    return end - start > _EPSILON


def _validate_selectable(candidate: Mapping[str, Any]) -> None:
    review = candidate.get("review")
    if not isinstance(review, Mapping) or not candidate.get("reviewSha256"):
        raise PersianAssetWorkspaceError("asset candidate must be reviewed before selection")
    if review.get("affect_match") is not True:
        raise PersianAssetWorkspaceError("asset candidate affect_match must be true before selection")
    if str(review.get("staged_stock_risk") or "") == "high":
        raise PersianAssetWorkspaceError("high staged_stock_risk candidate cannot be selected")
    geometry = review.get("geometry_review") or {}
    if geometry.get("crop_safe") is not True:
        raise PersianAssetWorkspaceError("asset candidate crop must be reviewed as safe before selection")
    if not str(review.get("relevance_reason") or "").strip():
        raise PersianAssetWorkspaceError("asset candidate requires semantic relevance evidence")



def _manifest_binding(candidate: Mapping[str, Any]) -> dict[str, Any]:
    identity = candidate.get("identity") if isinstance(candidate.get("identity"), Mapping) else {}
    window = identity.get("sourceWindow") if isinstance(identity.get("sourceWindow"), Mapping) else {}
    start = float(window.get("startSeconds") or 0.0)
    end = float(window.get("endSeconds") or 0.0)
    return {
        "asset_candidate_id": str(candidate.get("candidateId") or ""),
        "asset_candidate_identity_sha256": str(candidate.get("identitySha256") or ""),
        "asset_review_sha256": str(candidate.get("reviewSha256") or ""),
        "provider": str(identity.get("provider") or ""),
        "source_id": str(identity.get("sourceId") or ""),
        "source_in_seconds": round(start, 6),
        "source_window_end_seconds": round(end, 6),
        "duration_seconds": round(float((candidate.get("source") or {}).get("durationSeconds") or 0.0), 6),
        "intended_crop": dict(identity.get("intendedCrop") or {}),
    }



def _manifest_evidence(candidate: Mapping[str, Any]) -> dict[str, Any]:
    context = candidate.get("context") if isinstance(candidate.get("context"), Mapping) else {}
    review = candidate.get("review") if isinstance(candidate.get("review"), Mapping) else {}
    return {
        "visual_event_id": str(context.get("visualEventId") or ""),
        "semantic_beat_id": str(context.get("semanticBeatId") or ""),
        "query": str(context.get("query") or ""),
        "candidate_rank": int(context.get("candidateRank") or 0),
        "narration_span": str(context.get("narrationSpan") or ""),
        "selection_reason": str(review.get("selection_reason") or ""),
        "relevance_reason": str(review.get("relevance_reason") or ""),
        "affect_match": review.get("affect_match"),
        "staged_stock_risk": str(review.get("staged_stock_risk") or ""),
        "human_presence": review.get("human_presence"),
        "shows_subject": review.get("shows_subject"),
        "frame_review": dict(review.get("frame_review") or {}),
    }



def _same_number(left: object, right: object) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return False


def validate_asset_manifest_against_workspace(
    project_dir: Path, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Verify canonical selected rows against durable workspace selection identity.

    The workspace is review/history state, not a second asset manifest.  When it has
    no selections this validator is intentionally a no-op for legacy projects.  Once
    selections exist, every selected visual event must bind its canonical manifest
    row to the exact reviewed provider/source/window/crop identity.
    """
    selections = _read_selections(project_dir)
    if not selections:
        discovery_root = _discovery_root(project_dir) / "candidates"
        candidate_root = _root(project_dir) / "candidates"
        workspace_active = (
            (discovery_root.is_dir() and any(discovery_root.glob("*.json")))
            or (candidate_root.is_dir() and any(candidate_root.glob("asset-*.json")))
        )
        if workspace_active:
            raise PersianAssetWorkspaceError(
                "asset workspace has discovered/staged candidates but no selected candidates; "
                "select reviewed candidates before writing the canonical asset_manifest"
            )
        return {"enforced": False, "selectedCount": 0, "validatedVisualEventIds": []}
    if not isinstance(manifest, Mapping):
        raise PersianAssetWorkspaceError("canonical asset_manifest must be an object")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise PersianAssetWorkspaceError("canonical asset_manifest.assets must be a list")

    by_event: dict[str, list[Mapping[str, Any]]] = {}
    for raw in assets:
        if not isinstance(raw, Mapping):
            continue
        event_id = str(raw.get("visual_event_id") or "").strip()
        if event_id:
            by_event.setdefault(event_id, []).append(raw)

    unselected_events = sorted(set(by_event) - set(selections))
    if unselected_events:
        raise PersianAssetWorkspaceError(
            "asset_manifest contains visual_event_id rows not selected in the asset workspace: "
            + ", ".join(unselected_events)
        )

    validated: list[str] = []
    for event_id, selection in selections.items():
        rows = by_event.get(event_id) or []
        if len(rows) != 1:
            raise PersianAssetWorkspaceError(
                f"asset_manifest must contain exactly one selected row for visual_event_id {event_id!r}; got {len(rows)}"
            )
        row = rows[0]
        candidate = load_asset_candidate(
            project_dir, str(selection.get("candidateId") or "")
        )
        expected = _manifest_binding(candidate)
        for field in (
            "asset_candidate_id",
            "asset_candidate_identity_sha256",
            "asset_review_sha256",
            "source_id",
        ):
            actual = str(row.get(field) or "")
            if actual != str(expected[field]):
                raise PersianAssetWorkspaceError(
                    f"asset_manifest {event_id!r} {field} does not match selected workspace candidate"
                )
        try:
            actual_provider = _provider(row.get("provider"))
        except PersianAssetWorkspaceError as exc:
            raise PersianAssetWorkspaceError(
                f"asset_manifest {event_id!r} provider does not match selected workspace candidate"
            ) from exc
        if actual_provider != expected["provider"]:
            raise PersianAssetWorkspaceError(
                f"asset_manifest {event_id!r} provider does not match selected workspace candidate"
            )
        for field in (
            "source_in_seconds", "source_window_end_seconds", "duration_seconds"
        ):
            if not _same_number(row.get(field), expected[field]):
                raise PersianAssetWorkspaceError(
                    f"asset_manifest {event_id!r} {field} does not match selected workspace candidate"
                )
        expected_evidence = _manifest_evidence(candidate)
        for field in (
            "visual_event_id", "semantic_beat_id", "query", "narration_span",
            "selection_reason", "relevance_reason", "staged_stock_risk",
        ):
            if str(row.get(field) or "") != str(expected_evidence[field]):
                raise PersianAssetWorkspaceError(
                    f"asset_manifest {event_id!r} {field} does not match persisted candidate review/context"
                )
        if int(row.get("candidate_rank") or 0) != int(expected_evidence["candidate_rank"]):
            raise PersianAssetWorkspaceError(
                f"asset_manifest {event_id!r} candidate_rank does not match persisted candidate context"
            )
        for field in ("affect_match", "human_presence", "shows_subject"):
            if row.get(field) is not expected_evidence[field]:
                raise PersianAssetWorkspaceError(
                    f"asset_manifest {event_id!r} {field} does not match persisted candidate review"
                )
        if row.get("frame_review") != expected_evidence["frame_review"]:
            raise PersianAssetWorkspaceError(
                f"asset_manifest {event_id!r} frame_review does not match persisted candidate review"
            )

        raw_crop = row.get("intended_crop")
        if not isinstance(raw_crop, Mapping):
            raise PersianAssetWorkspaceError(
                f"asset_manifest {event_id!r} intended_crop is required for workspace-bound selection"
            )
        actual_crop = _normalize_crop(raw_crop)
        if actual_crop != expected["intended_crop"]:
            raise PersianAssetWorkspaceError(
                f"asset_manifest {event_id!r} intended_crop does not match selected workspace candidate"
            )
        validated.append(event_id)

    return {
        "enforced": True,
        "selectedCount": len(selections),
        "validatedVisualEventIds": sorted(validated),
    }



def select_asset_candidate(
    project_dir: Path,
    visual_event_id: str,
    candidate_id: str,
    *,
    rejected_alternatives: Mapping[str, str],
    replace_existing: bool = False,
) -> dict[str, Any]:
    event_id = str(visual_event_id or "").strip()
    candidate = load_asset_candidate(project_dir, candidate_id)
    if str((candidate.get("context") or {}).get("visualEventId") or "") != event_id:
        raise PersianAssetWorkspaceError("candidate visual event does not match selection target")
    if candidate.get("disposition") == "rejected":
        raise PersianAssetWorkspaceError("rejected asset candidate cannot be selected")
    _validate_selectable(candidate)

    selections = _read_selections(project_dir)
    existing = selections.get(event_id)
    if existing and existing.get("candidateId") == candidate_id:
        return {
            "selected": False, "idempotent": True, "selection": existing,
            "manifestBinding": _manifest_binding(candidate),
            "manifestEvidence": _manifest_evidence(candidate),
        }
    if existing and not replace_existing:
        raise PersianAssetWorkspaceError(
            f"visual event {event_id!r} already has a selected candidate; use replace_existing"
        )

    for other_event, selection in selections.items():
        if other_event == event_id:
            continue
        other = load_asset_candidate(project_dir, str(selection.get("candidateId") or ""))
        left = candidate.get("identity") or {}
        right = other.get("identity") or {}
        if (
            left.get("provider") == right.get("provider")
            and left.get("sourceId") == right.get("sourceId")
            and _windows_overlap(left, right)
        ):
            raise PersianAssetWorkspaceError(
                "visible source-window overlap with already selected candidate "
                f"for {other_event!r}"
            )

    provided = {
        str(key): str(reason or "").strip()
        for key, reason in dict(rejected_alternatives or {}).items()
    }
    reviewed_alternates = [
        item for item in _candidate_records(project_dir)
        if item.get("candidateId") != candidate_id
        and str((item.get("context") or {}).get("visualEventId") or "") == event_id
        and item.get("reviewSha256")
    ]
    rejected_reasons: dict[str, str] = {}
    missing: list[str] = []
    for alternate in reviewed_alternates:
        alternate_id = str(alternate["candidateId"])
        persisted = alternate.get("rejection")
        reason = provided.get(alternate_id) or (
            str((persisted or {}).get("reason") or "") if isinstance(persisted, Mapping) else ""
        )
        if not reason:
            missing.append(alternate_id)
        else:
            rejected_reasons[alternate_id] = reason
    if missing:
        raise PersianAssetWorkspaceError(
            "reviewed alternatives require rejection reasons before selection: "
            + ", ".join(sorted(missing))
        )

    previous_candidate_id = str((existing or {}).get("candidateId") or "")
    if previous_candidate_id and previous_candidate_id != candidate_id:
        previous = load_asset_candidate(project_dir, previous_candidate_id)
        previous["disposition"] = "reviewed"
        previous["updatedAt"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(_candidate_path(project_dir, previous_candidate_id), previous)

    selection = {
        "visualEventId": event_id,
        "candidateId": candidate_id,
        "candidateIdentitySha256": candidate["identitySha256"],
        "reviewSha256": candidate["reviewSha256"],
        "rejectedAlternatives": rejected_reasons,
        "selectedAt": datetime.now(timezone.utc).isoformat(),
    }
    selections[event_id] = selection
    _write_selections(project_dir, selections)
    candidate["disposition"] = "selected"
    candidate["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(_candidate_path(project_dir, candidate_id), candidate)
    return {
        "selected": True, "idempotent": False, "selection": selection,
        "manifestBinding": _manifest_binding(candidate),
        "manifestEvidence": _manifest_evidence(candidate),
    }


def asset_workspace_status(project_dir: Path) -> dict[str, Any]:
    root = _root(project_dir)
    passes = sorted((_discovery_root(project_dir) / "passes").glob("pass-*.json")) if root.exists() else []
    discoveries = sorted((_discovery_root(project_dir) / "candidates").glob("*.json")) if root.exists() else []
    candidates = _candidate_records(project_dir)
    selections = _read_selections(project_dir)
    rejection_counts = {key: 0 for key in sorted(_REJECTION_CATEGORIES)}
    for candidate in candidates:
        rejection = candidate.get("rejection")
        if isinstance(rejection, Mapping):
            category = str(rejection.get("category") or "")
            if category in rejection_counts:
                rejection_counts[category] += 1

    weak_warnings: list[dict[str, Any]] = []
    for event_id, selection in selections.items():
        candidate = load_asset_candidate(project_dir, str(selection.get("candidateId") or ""))
        role = str((candidate.get("context") or {}).get("narrativeRole") or "").strip().lower()
        review = candidate.get("review") or {}
        if role in {"resolution", "ending", "closing"} and review.get("resolution_quality") == "weak":
            weak_warnings.append({
                "visualEventId": event_id,
                "candidateId": candidate["candidateId"],
                "reason": "weak_resolution_quality",
            })

    reusable_events = sorted({
        str((candidate.get("context") or {}).get("visualEventId") or "").strip()
        for candidate in candidates
        if candidate.get("reviewSha256") and candidate.get("disposition") != "rejected"
    } - {""})
    reusable_by_event = {
        event_id: reusable_asset_candidates(project_dir, visual_event_id=event_id)
        for event_id in reusable_events
    }

    return {
        "version": "1.0",
        "discoveryPassCount": len(passes),
        "discoveryCandidateCount": len(discoveries),
        "candidateCount": len(candidates),
        "reviewedCandidateCount": sum(1 for item in candidates if item.get("reviewSha256")),
        "selectedCount": len(selections),
        "selectedCandidateIds": {
            event_id: str(selection.get("candidateId") or "")
            for event_id, selection in selections.items()
        },
        "rejectionCounts": rejection_counts,
        "reusableCandidatesByVisualEvent": reusable_by_event,
        "weakSelectionWarnings": weak_warnings,
    }


__all__ = [
    "PersianAssetWorkspaceError",
    "asset_workspace_status",
    "load_asset_candidate",
    "record_candidate_review",
    "record_discovery_pass",
    "reject_asset_candidate",
    "reusable_asset_candidates",
    "select_asset_candidate",
    "stage_asset_candidate",
    "validate_asset_manifest_against_workspace",
]
