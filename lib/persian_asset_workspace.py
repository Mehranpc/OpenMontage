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
import re
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
_REVIEWED_DECLARATION_FIELDS = (
    "fallback_level", "fallback_reason", "semantic_role", "semantic_direction",
    "opening_semantic_match",
)


class PersianAssetWorkspaceError(ValueError):
    pass


class AssetAdmissionRefused(PersianAssetWorkspaceError):
    """Selection refused before any write; ``diagnostics`` lists every known blocker (#360)."""

    def __init__(self, message: str, diagnostics: Sequence[Mapping[str, Any]]):
        super().__init__(message)
        self.diagnostics = [dict(item) for item in diagnostics]


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



def _source_tags(value: object) -> list[str]:
    """Provider tags as a list of phrases (#266).

    Stock sources return one string (``Candidate.source_tags: str``); ``list()`` of
    it stored every character as a tag. Split on commas/newlines, and keep a
    phrase whole when there is no separator. Lists pass through, stripped.
    """
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\n;|]", value)
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
        if items and all(len(item) <= 1 for item in items):
            # A record written before this fix: the characters of one string.
            return _source_tags("".join(items))
        return [item.strip() for item in items if item.strip()]
    return []

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
            "sourceTags": _source_tags(raw.get("source_tags")),
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
            "sourceTags": _source_tags(discovery.get("sourceTags")),
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


def _validate_manifest_frame_review(frame: Mapping[str, Any]) -> None:
    """Use the canonical frame contract for admission and legacy projection (#358)."""
    from jsonschema import ValidationError, validate
    from schemas.artifacts import load_schema

    schema = load_schema("asset_manifest")["properties"]["assets"]["items"]["properties"]["frame_review"]
    try:
        validate(instance=dict(frame), schema=schema)
    except ValidationError as exc:
        raise PersianAssetWorkspaceError(
            f"frame_review violates the asset_manifest contract: {exc.message}"
        ) from exc


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
    if "placement_space" in frame:
        from lib.persian_scenes import NEGATIVE_SPACE_REGIONS

        placement = frame.get("placement_space")
        if placement not in NEGATIVE_SPACE_REGIONS:
            raise PersianAssetWorkspaceError(
                f"frame_review.placement_space {placement!r} is not one of "
                f"{sorted(NEGATIVE_SPACE_REGIONS)}; omit the field for an event that carries "
                "no typographic moment instead of writing a placeholder such as 'none' (#337)"
            )
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
    if "fallback_level" in result or "fallback_reason" in result:
        # The treatment level is observed from the clip, so it may be reviewed evidence
        # that admission compares with the plan instead of a build-time label (#360).
        from lib.persian_scenes import FALLBACK_LEVELS

        level = str(result.get("fallback_level") or "").strip()
        if level not in FALLBACK_LEVELS:
            raise PersianAssetWorkspaceError(
                f"fallback_level must be one of {', '.join(FALLBACK_LEVELS)}"
            )
        result["fallback_level"] = level
        reason = str(result.get("fallback_reason") or "").strip()
        if level != "exact_literal" and not reason:
            raise PersianAssetWorkspaceError(
                "non-literal fallback_level requires fallback_reason documenting why earlier levels failed"
            )
        if reason:
            result["fallback_reason"] = reason
        else:
            result.pop("fallback_reason", None)
    for field in ("semantic_role", "semantic_direction"):
        if field in result and (not isinstance(result[field], str) or not result[field].strip()):
            raise PersianAssetWorkspaceError(f"{field} must be a non-empty string")
    if "opening_semantic_match" in result and not isinstance(result["opening_semantic_match"], bool):
        raise PersianAssetWorkspaceError("opening_semantic_match must be boolean")
    _validate_manifest_frame_review(frame)
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
    selected_events = sorted(
        event for event, item in selections.items() if item.get("candidateId") == candidate_id
    )
    released: list[str] = []
    if selected_events:
        # A selection the admission rules now refuse may be rejected directly, which
        # reopens its event for the retry route; a valid one must still be replaced (#360).
        try:
            admission = assess_candidate_admission(
                project_dir, selected_events[0], candidate, selections=selections
            )
            failing = admission["diagnostics"]
        except PersianAssetWorkspaceError as exc:
            failing = [{"code": "EVIDENCE_UNPROJECTABLE", "message": str(exc)}]
        if not failing:
            raise PersianAssetWorkspaceError("selected candidate must be replaced before rejection")
        released = selected_events
        for event in released:
            selections.pop(event)
        _write_selections(project_dir, selections)
    candidate["rejection"] = {
        "category": normalized_category,
        "reason": clean_reason,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if released:
        candidate["rejection"]["releasedSelections"] = released
        candidate["rejection"]["admissionCodes"] = sorted({str(item.get("code")) for item in failing})
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


def _require_reviewed(candidate: Mapping[str, Any]) -> None:
    review = candidate.get("review")
    if not isinstance(review, Mapping) or not candidate.get("reviewSha256"):
        raise PersianAssetWorkspaceError("asset candidate must be reviewed before selection")


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



def _manifest_frame_review(raw: object) -> dict[str, Any]:
    """The review's frame evidence as the manifest carries it.

    Review evidence is immutable, and before #337 a review could persist
    ``placement_space: "none"`` for an event with no moment. The manifest schema accepts
    only a real region there, so the whole build was refused and the only repair was a
    full send-back. A placeholder was never evidence of a clear region: leave it out. A
    carrier that lacks a real one still fails the carrier check, which asks for it.
    Before #358, misplaced boolean ``face_visible`` was also admitted here; it
    belongs to subject-region review. Project it out without rewriting durable
    evidence, then validate every remaining field against the canonical schema.
    """
    from lib.persian_scenes import NEGATIVE_SPACE_REGIONS

    frame = dict(raw) if isinstance(raw, Mapping) else {}
    if "placement_space" in frame and frame["placement_space"] not in NEGATIVE_SPACE_REGIONS:
        frame.pop("placement_space")
    if "face_visible" in frame:
        # Older admission accepted this subject-region annotation here. Preserve
        # raw review bytes/hash; it is not canonical frame evidence or a substitute
        # for the later subject-region review. Unknown fields remain hard errors.
        if not isinstance(frame["face_visible"], bool):
            raise PersianAssetWorkspaceError("legacy frame_review.face_visible must be boolean")
        frame.pop("face_visible")
    _validate_manifest_frame_review(frame)
    return frame


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
        "frame_review": _manifest_frame_review(review.get("frame_review")),
        **_reviewed_fallback(review),
        **{field: review[field] for field in (
            "semantic_role", "semantic_direction", "opening_semantic_match",
        ) if field in review},
    }


def _reviewed_fallback(review: Mapping[str, Any]) -> dict[str, Any]:
    """Fallback evidence recorded in the review, if any; legacy reviews record none."""
    from lib.persian_scenes import FALLBACK_LEVELS

    level = str(review.get("fallback_level") or "").strip()
    if level not in FALLBACK_LEVELS:
        return {}
    evidence: dict[str, Any] = {"fallback_level": level}
    reason = str(review.get("fallback_reason") or "").strip()
    if reason:
        evidence["fallback_reason"] = reason
    return evidence



def _same_number(left: object, right: object) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return False


def validate_edit_asset_bindings(
    project_dir: Path,
    edit: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    required_shot_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Bind edit shots to exact immutable reviewed asset-workspace identities."""
    if not isinstance(request, Mapping) or str(request.get("version") or "") != "1.0":
        raise PersianAssetWorkspaceError(
            "edit asset binding request must be an object with version='1.0'"
        )
    raw_bindings = request.get("shotBindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise PersianAssetWorkspaceError(
            "edit asset binding request requires a non-empty shotBindings list"
        )
    persian = edit.get("persian") if isinstance(edit.get("persian"), Mapping) else {}
    raw_shots = persian.get("shots") if isinstance(persian, Mapping) else None
    if not isinstance(raw_shots, list):
        raise PersianAssetWorkspaceError("edit asset binding requires persian.shots")
    shots = {
        str(shot.get("id") or ""): shot
        for shot in raw_shots
        if isinstance(shot, Mapping) and str(shot.get("id") or "").strip()
    }
    required = {str(item) for item in required_shot_ids if str(item).strip()}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    root = project_dir.expanduser().resolve()
    for index, raw in enumerate(raw_bindings):
        if not isinstance(raw, Mapping):
            raise PersianAssetWorkspaceError(
                f"shotBindings[{index}] must be an object"
            )
        shot_id = str(raw.get("shotId") or "").strip()
        candidate_id = str(raw.get("candidateId") or "").strip()
        if not shot_id or not candidate_id:
            raise PersianAssetWorkspaceError(
                f"shotBindings[{index}] requires shotId and candidateId"
            )
        if shot_id in seen:
            raise PersianAssetWorkspaceError(f"duplicate edit asset binding for {shot_id!r}")
        seen.add(shot_id)
        shot = shots.get(shot_id)
        if not isinstance(shot, Mapping):
            raise PersianAssetWorkspaceError(
                f"edit asset binding references unknown shot {shot_id!r}"
            )
        candidate = load_asset_candidate(project_dir, candidate_id)
        if candidate.get("disposition") == "rejected" or not candidate.get("reviewSha256"):
            raise PersianAssetWorkspaceError(
                f"edit asset binding candidate {candidate_id!r} must have immutable review evidence"
            )
        event_id = str(shot.get("visualEventId") or "").strip()
        candidate_event = str((candidate.get("context") or {}).get("visualEventId") or "").strip()
        if not event_id or candidate_event != event_id:
            raise PersianAssetWorkspaceError(
                f"edit shot {shot_id!r} visual event does not match candidate {candidate_id!r}"
            )
        source_value = str(shot.get("source") or shot.get("src") or "").strip()
        candidate_source = str((candidate.get("source") or {}).get("path") or "").strip()
        if not source_value or not candidate_source:
            raise PersianAssetWorkspaceError(
                f"edit shot {shot_id!r} and candidate {candidate_id!r} require source paths"
            )
        edit_path = Path(source_value).expanduser()
        edit_path = edit_path.resolve() if edit_path.is_absolute() else (root / edit_path).resolve()
        candidate_path = Path(candidate_source).expanduser().resolve()
        if edit_path != candidate_path:
            raise PersianAssetWorkspaceError(
                f"edit shot {shot_id!r} source does not match reviewed candidate {candidate_id!r}"
            )
        try:
            timeline_start = float(shot.get("startSeconds") or 0.0)
            timeline_end = float(shot.get("endSeconds") or 0.0)
            source_start = float(shot.get("sourceInSeconds") or 0.0)
        except (TypeError, ValueError) as exc:
            raise PersianAssetWorkspaceError(
                f"edit shot {shot_id!r} has invalid source-window timing"
            ) from exc
        duration = timeline_end - timeline_start
        if duration <= 0:
            raise PersianAssetWorkspaceError(
                f"edit shot {shot_id!r} must have positive timeline duration"
            )
        edit_window = {
            "startSeconds": round(source_start, 6),
            "endSeconds": round(source_start + duration, 6),
        }
        identity = candidate.get("identity") if isinstance(candidate.get("identity"), Mapping) else {}
        candidate_window = identity.get("sourceWindow") if isinstance(identity, Mapping) else None
        if not isinstance(candidate_window, Mapping) or {
            "startSeconds": round(float(candidate_window.get("startSeconds") or 0.0), 6),
            "endSeconds": round(float(candidate_window.get("endSeconds") or 0.0), 6),
        } != edit_window:
            raise PersianAssetWorkspaceError(
                f"edit shot {shot_id!r} source window is absent from reviewed candidate {candidate_id!r}"
            )
        crop = identity.get("intendedCrop") if isinstance(identity, Mapping) else None
        if not isinstance(crop, Mapping):
            raise PersianAssetWorkspaceError(
                f"reviewed candidate {candidate_id!r} is missing crop identity"
            )
        normalized.append({
            "shotId": shot_id,
            "visualEventId": event_id,
            "candidateId": candidate_id,
            "candidateIdentitySha256": str(candidate.get("identitySha256") or ""),
            "reviewSha256": str(candidate.get("reviewSha256") or ""),
            "manifestBinding": _manifest_binding(candidate),
        })
    if required:
        missing = sorted(required - seen)
        extra = sorted(seen - required)
        if missing or extra:
            raise PersianAssetWorkspaceError(
                "edit asset bindings must cover exactly the asset-changed shots; "
                f"missing={missing}, extra={extra}"
            )
    return sorted(normalized, key=lambda item: item["shotId"])


def validate_edit_asset_bindings_against_manifest(
    project_dir: Path,
    bindings: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Require promoted edit bindings to equal the selected canonical manifest."""
    validated = validate_asset_manifest_against_workspace(project_dir, manifest)
    rows = manifest.get("assets") if isinstance(manifest, Mapping) else None
    if not isinstance(rows, list):
        raise PersianAssetWorkspaceError("canonical asset_manifest.assets must be a list")
    by_event: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if isinstance(row, Mapping):
            by_event.setdefault(str(row.get("visual_event_id") or ""), []).append(row)
    for binding in bindings:
        event_id = str(binding.get("visualEventId") or "")
        candidate_id = str(binding.get("candidateId") or "")
        matches = by_event.get(event_id) or []
        if len(matches) != 1:
            raise PersianAssetWorkspaceError(
                f"asset_manifest must contain exactly one row for bound visual event {event_id!r}"
            )
        row = matches[0]
        expected = {
            "asset_candidate_id": candidate_id,
            "asset_candidate_identity_sha256": str(binding.get("candidateIdentitySha256") or ""),
            "asset_review_sha256": str(binding.get("reviewSha256") or ""),
        }
        for field, value in expected.items():
            if str(row.get(field) or "") != value:
                raise PersianAssetWorkspaceError(
                    f"asset_manifest {event_id!r} {field} does not match the edit-bound reviewed candidate"
                )
    return {**validated, "validatedEditBindingCount": len(bindings)}


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
        for field in _REVIEWED_DECLARATION_FIELDS:
            if field in expected_evidence and row.get(field) != expected_evidence[field]:
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



def _admission_requirement(
    project_dir: Path, event_id: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The planned requirement for ``event_id`` from the effective plan, read-only (#360)."""
    from lib.persian_assets import recovery_options, scene_asset_requirements
    from lib.persian_scene_plan_source import ScenePlanUnreadable, load_effective_scene_plan

    def refusal(code: str, message: str) -> list[dict[str, Any]]:
        item = {
            "code": code, "ruleClass": "event_local", "visualEventId": event_id,
            "field": None, "expected": None, "observed": None, "message": message,
        }
        return [{**item, "recovery": recovery_options(item)}]

    try:
        plan = load_effective_scene_plan(project_dir)
    except ScenePlanUnreadable as exc:
        return None, refusal("PLAN_INVALID", f"{event_id}: {exc}; admission cannot check the plan")
    if plan is None:
        return None, refusal(
            "PLAN_MISSING",
            f"{event_id}: no completed scene plan; a selection cannot be checked against "
            "its planned visual event",
        )
    try:
        requirements, typographic_ids, _ = scene_asset_requirements(plan)
    except (AttributeError, TypeError, ValueError) as exc:
        return None, refusal("PLAN_INVALID", f"{event_id}: scene plan is malformed ({exc})")
    for requirement in requirements:
        if str(requirement.get("visual_event_id") or "") == event_id:
            return requirement, []
    return None, refusal(
        "EVENT_NOT_IN_PLAN", f"visual_event_id {event_id!r} is not present in the scene plan"
    )


def assess_candidate_admission(
    project_dir: Path,
    visual_event_id: str,
    candidate: Mapping[str, Any],
    *,
    selections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Every blocker already provable for selecting ``candidate``; never writes (#360).

    Uses the manifest audit's own rules on the row the build would produce, plus the
    current-set source-window rule. Missing future events are completion rules and are
    not checked here.
    """
    from lib.persian_assets import assess_selection_entry, recovery_options

    event_id = str(visual_event_id or "").strip()
    candidate_id = str(candidate.get("candidateId") or "")
    requirement, diagnostics = _admission_requirement(project_dir, event_id)
    declarations: list[dict[str, Any]] = []
    if requirement is not None:
        row = _manifest_row(candidate)
        if (
            "fallback_level" not in _reviewed_fallback(candidate.get("review") or {})
            and str(requirement.get("fallback_level") or "").strip() != "exact_literal"
        ):
            # The build's exact_literal default is a declaration, not reviewed evidence;
            # it satisfies only a literal plan.
            row.pop("fallback_level", None)
        assessed = assess_selection_entry(row, requirement)
        diagnostics.extend(assessed["diagnostics"])
        declarations = assessed["declarationsRequired"]
    review = candidate.get("review") if isinstance(candidate.get("review"), Mapping) else {}
    geometry = review.get("geometry_review") if isinstance(review.get("geometry_review"), Mapping) else {}
    if geometry.get("crop_safe") is not True:
        item = {
            "code": "CROP_UNSAFE", "ruleClass": "event_local", "visualEventId": event_id,
            "field": "geometry_review.crop_safe", "expected": True,
            "observed": geometry.get("crop_safe"),
            "message": f"{event_id}: asset candidate crop must be reviewed as safe before selection",
        }
        diagnostics.append({**item, "recovery": recovery_options(item)})
    for other_event, selection in sorted(selections.items()):
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
            item = {
                "code": "SOURCE_WINDOW_OVERLAP", "ruleClass": "current_set",
                "visualEventId": event_id, "field": "identity.sourceWindow",
                "expected": "non-overlapping window",
                "observed": {"conflictsWith": other_event, "candidateId": other.get("candidateId")},
                "message": (
                    "visible source-window overlap with already selected candidate "
                    f"for {other_event!r}"
                ),
            }
            diagnostics.append({**item, "recovery": recovery_options(item)})
    from lib.persian_assets import _diagnostic_sort_key

    for item in [*diagnostics, *declarations]:
        item["candidateId"] = candidate_id
        item["reviewSha256"] = str(candidate.get("reviewSha256") or "")
    diagnostics.sort(key=_diagnostic_sort_key)
    return {
        "visualEventId": event_id,
        "candidateId": candidate_id,
        "admissible": not diagnostics,
        "diagnostics": diagnostics,
        "declarationsRequired": declarations,
    }


def _refuse(event_id: str, candidate_id: str, diagnostics: Sequence[Mapping[str, Any]]) -> None:
    raise AssetAdmissionRefused(
        f"asset selection refused for {event_id!r} ({candidate_id}); nothing was written: "
        + " | ".join(f"[{item['code']}] {item['message']}" for item in diagnostics),
        diagnostics,
    )


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
    _require_reviewed(candidate)
    # Admission must precede every selection/candidate write, including legacy records.
    manifest_evidence = _manifest_evidence(candidate)

    selections = _read_selections(project_dir)
    existing = selections.get(event_id)
    # Idempotent and replacement paths are admitted by the same rules: re-selecting an
    # incompatible legacy selection must not read as a clean no-op (#360).
    admission = assess_candidate_admission(
        project_dir, event_id, candidate, selections=selections
    )
    diagnostics = list(admission["diagnostics"])

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
    is_idempotent = bool(existing and existing.get("candidateId") == candidate_id)
    if missing and not is_idempotent:
        diagnostics.append({
            "code": "ALTERNATE_REASONS_MISSING", "ruleClass": "selection_protocol",
            "visualEventId": event_id, "candidateId": candidate_id,
            "field": "rejected_alternatives", "expected": sorted(missing), "observed": sorted(provided),
            "message": (
                "reviewed alternatives require rejection reasons before selection: "
                + ", ".join(sorted(missing))
            ),
            "recovery": ["record_alternate_rejection_reasons"],
        })
    if diagnostics:
        _refuse(event_id, candidate_id, diagnostics)

    if is_idempotent:
        return {
            "selected": False, "idempotent": True, "selection": existing,
            "manifestBinding": _manifest_binding(candidate),
            "manifestEvidence": manifest_evidence,
            "declarationsRequired": admission["declarationsRequired"],
        }
    if existing and not replace_existing:
        raise PersianAssetWorkspaceError(
            f"visual event {event_id!r} already has a selected candidate; use replace_existing"
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
        "manifestEvidence": manifest_evidence,
        "declarationsRequired": admission["declarationsRequired"],
    }


def _manifest_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """The canonical row a selected candidate becomes, before build overrides (#360).

    Admission audits exactly this row, so selection and the manifest cannot disagree
    about a fact the durable candidate already records.
    """
    source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
    evidence = _manifest_evidence(candidate)
    binding = _manifest_binding(candidate)
    provider = str(binding["provider"])
    creator = str(source.get("creator") or "").strip()
    provider_label = "Pexels" if provider == "pexels" else "Pixabay"
    raw_license = source.get("license")
    if isinstance(raw_license, Mapping):
        license_name = str(raw_license.get("name") or "").strip()
    else:
        license_name = str(raw_license or "").strip()
    if not license_name:
        license_name = f"{provider_label} License"
    row: dict[str, Any] = {
        **binding,
        **evidence,
        "id": binding["asset_candidate_id"],
        "type": "video",
        "kind": "video",
        "source_tool": "direct_clip_search",
        "scene_id": evidence["semantic_beat_id"],
        "beat_id": evidence["semantic_beat_id"],
        "path": str(source.get("path") or ""),
        "width": int(source.get("width") or 0),
        "height": int(source.get("height") or 0),
        "original_url": str(source.get("originalUrl") or ""),
        "license": license_name,
        "attribution": (
            f"Video by {creator} on {provider_label}"
            if creator else f"Video on {provider_label}"
        ),
        "fallback_level": evidence.get("fallback_level", "exact_literal"),
    }
    return row


def build_asset_manifest_from_workspace(
    project_dir: Path,
    *,
    video_format: str = "vertical",
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build canonical rows from the durable selection ledger, never a second ledger."""
    clean_format = str(video_format or "").strip().lower()
    if clean_format not in {"vertical", "landscape", "square"}:
        raise PersianAssetWorkspaceError("video_format must be vertical, landscape, or square")
    selections = _read_selections(project_dir)
    if not selections:
        raise PersianAssetWorkspaceError(
            "asset workspace has no selected candidates; select reviewed candidates first"
        )
    options = dict(overrides or {})
    per_event = options.pop("assets", {})
    if not isinstance(per_event, Mapping):
        raise PersianAssetWorkspaceError("manifest overrides.assets must be an object")
    unknown = sorted(set(per_event) - set(selections))
    if unknown:
        raise PersianAssetWorkspaceError(
            "manifest overrides reference unselected visual events: " + ", ".join(unknown)
        )

    assets: list[dict[str, Any]] = []
    for event_id in sorted(selections):
        selection = selections[event_id]
        candidate = load_asset_candidate(
            project_dir, str(selection.get("candidateId") or "")
        )
        evidence = _manifest_evidence(candidate)
        row = _manifest_row(candidate)
        event_override = per_event.get(event_id, {})
        if not isinstance(event_override, Mapping):
            raise PersianAssetWorkspaceError(
                f"manifest override for {event_id!r} must be an object"
            )
        allowed_override_fields = {
            "attribution", "fallback_level", "fallback_reason", "license",
            "opening_semantic_match", "semantic_direction", "semantic_role",
        }
        unsupported_fields = sorted(set(event_override) - allowed_override_fields)
        if unsupported_fields:
            raise PersianAssetWorkspaceError(
                f"manifest override for {event_id!r} cannot replace canonical fields: "
                + ", ".join(unsupported_fields)
            )
        for field in _REVIEWED_DECLARATION_FIELDS:
            if field in evidence and field in event_override and event_override[field] != evidence[field]:
                raise PersianAssetWorkspaceError(
                    f"manifest override for {event_id!r} cannot replace reviewed {field} "
                    f"{evidence[field]!r}; reconcile-plan the event or select another candidate"
                )
        row.update({str(key): value for key, value in event_override.items()})
        assets.append(row)

    manifest: dict[str, Any] = {
        "version": "1.0",
        "format": clean_format,
        "assets": assets,
        "metadata": {"project_id": project_dir.name},
    }
    for key in ("music", "musicTrack", "word_timings", "total_cost_usd"):
        if key in options:
            manifest[key] = options[key]
    if "total_cost_usd" not in manifest:
        # The delivery-quality producer reads spend from the assets checkpoint. Without
        # a total here, cost was always "missing" and every report blocked, although
        # stock footage and Pixabay music cost nothing. Derive it from the rows (#234).
        manifest["total_cost_usd"] = round(sum(
            float(row.get("cost_usd") or 0.0) for row in assets if isinstance(row, Mapping)
        ), 6)
    if "metadata" in options:
        if not isinstance(options["metadata"], Mapping):
            raise PersianAssetWorkspaceError("manifest overrides.metadata must be an object")
        manifest["metadata"].update(dict(options["metadata"]))
    unsupported = sorted(
        set(options) - {"music", "musicTrack", "word_timings", "total_cost_usd", "metadata"}
    )
    if unsupported:
        raise PersianAssetWorkspaceError(
            "unsupported manifest override keys: " + ", ".join(unsupported)
        )
    return manifest


def retry_readiness(project_dir: Path) -> dict[str, Any]:
    """What a retry pass must know before it may be spent (#239).

    Returns the staged candidates still awaiting review, the events that earlier passes
    found footage for but nobody has judged yet, and the events whose every staged
    candidate was rejected with no selection. A retry issued before
    review is how the single pass was spent on the wrong scope on the 58048e2 run.
    """
    candidates = _candidate_records(project_dir)
    selections = _read_selections(project_dir)
    unreviewed = sorted(
        str(item.get("candidateId") or "") for item in candidates
        if item.get("disposition") == "staged"
    )
    judged_events = {
        str((item.get("context") or {}).get("visualEventId") or "").strip()
        for item in candidates if item.get("disposition") in {"reviewed", "selected", "rejected"}
    }
    discovered_events: set[str] = set()
    discovery_dir = _discovery_root(project_dir) / "candidates"
    for path in sorted(discovery_dir.glob("*.json")) if discovery_dir.is_dir() else []:
        try:
            slot = str(json.loads(path.read_text(encoding="utf-8")).get("slotId") or "").strip()
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if slot:
            discovered_events.add(slot)
    unjudged_events = sorted(discovered_events - judged_events)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        event_id = str((item.get("context") or {}).get("visualEventId") or "").strip()
        if event_id:
            by_event.setdefault(event_id, []).append(item)
    blocked = sorted(
        event_id for event_id, items in by_event.items()
        if event_id not in selections and all(item.get("disposition") == "rejected" for item in items)
    )
    return {"unreviewedCandidateIds": unreviewed, "unjudgedDiscoveredEventIds": unjudged_events,
            "rejectedOnlyEventIds": blocked}


def selection_readiness(project_dir: Path) -> dict[str, Any]:
    """Recorded versus currently valid selections against the effective plan (#360).

    Read-only: evaluates recorded evidence with the admission rules and never touches
    the plan, ledger, candidates or artifacts. Counts are unique planned events. A
    ``ready_for_manifest*`` disposition needs every deterministic prerequisite passed.
    """
    from lib.persian_assets import ASSET_ADMISSION_POLICY_VERSION, scene_asset_requirements
    from lib.persian_scene_plan_source import ScenePlanUnreadable, load_effective_scene_plan

    selections = _read_selections(project_dir)
    plan_problem: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    try:
        plan = load_effective_scene_plan(project_dir)
    except ScenePlanUnreadable as exc:
        plan_problem = {"code": "PLAN_INVALID", "message": str(exc)}
    required: list[str] = []
    if plan is not None:
        try:
            requirements, _, _ = scene_asset_requirements(plan)
            required = sorted({
                str(item["visual_event_id"]) for item in requirements if item.get("visual_event_id")
            })
        except (AttributeError, TypeError, ValueError) as exc:
            plan_problem = {"code": "PLAN_INVALID", "message": f"scene plan is malformed ({exc})"}
    elif plan_problem is None:
        plan_problem = {"code": "PLAN_MISSING", "message": "no completed scene plan"}

    invalid: dict[str, list[dict[str, Any]]] = {}
    stale: dict[str, list[dict[str, Any]]] = {}
    declarations: dict[str, list[dict[str, Any]]] = {}
    bound: dict[str, dict[str, str]] = {}
    for event_id, selection in sorted(selections.items()):
        candidate_id = str(selection.get("candidateId") or "")
        try:
            candidate = load_asset_candidate(project_dir, candidate_id)
        except PersianAssetWorkspaceError as exc:
            stale[event_id] = [{"code": "SELECTION_CANDIDATE_MISSING", "candidateId": candidate_id,
                                "message": str(exc)}]
            continue
        bound[event_id] = {
            "candidateId": candidate_id,
            "candidateIdentitySha256": str(candidate.get("identitySha256") or ""),
            "reviewSha256": str(candidate.get("reviewSha256") or ""),
        }
        if (
            selection.get("candidateIdentitySha256") != candidate.get("identitySha256")
            or selection.get("reviewSha256") != candidate.get("reviewSha256")
        ):
            stale[event_id] = [{
                "code": "SELECTION_STALE", "candidateId": candidate_id,
                "expected": {"candidateIdentitySha256": selection.get("candidateIdentitySha256"),
                             "reviewSha256": selection.get("reviewSha256")},
                "observed": {"candidateIdentitySha256": candidate.get("identitySha256"),
                             "reviewSha256": candidate.get("reviewSha256")},
                "message": f"{event_id}: selection no longer binds its candidate's identity/review",
            }]
            continue
        if plan_problem is not None:
            continue
        try:
            admission = assess_candidate_admission(
                project_dir, event_id, candidate, selections=selections
            )
        except PersianAssetWorkspaceError as exc:
            invalid[event_id] = [{"code": "EVIDENCE_UNPROJECTABLE", "candidateId": candidate_id,
                                  "visualEventId": event_id, "message": str(exc),
                                  "recovery": ["reuse_reviewed_alternate", "reject_and_retry"]}]
            continue
        if admission["diagnostics"]:
            invalid[event_id] = admission["diagnostics"]
        if admission["declarationsRequired"]:
            declarations[event_id] = admission["declarationsRequired"]

    unresolved = [event for event in required if event not in selections]
    valid = [event for event in required if event in selections and event not in invalid and event not in stale]
    if plan_problem is not None:
        disposition = "plan_unavailable"
    elif stale:
        disposition = "stale_selections"
    elif invalid:
        disposition = "invalid_selections"
    elif unresolved:
        disposition = "incomplete"
    elif declarations:
        disposition = "ready_for_manifest_with_declarations"
    else:
        disposition = "ready_for_manifest"
    inputs = {
        "policyVersion": ASSET_ADMISSION_POLICY_VERSION,
        "scenePlanSha256": _sha256(plan) if plan is not None else None,
        "selections": bound,
    }
    return {
        "disposition": disposition,
        "requiredEventCount": len(required),
        "recordedSelectionCount": len(selections),
        "validSelectionCount": len(valid),
        "unresolvedEvents": unresolved,
        "invalidEvents": sorted(invalid),
        "staleEvents": sorted(stale),
        "declarationEvents": sorted(declarations),
        "planProblem": plan_problem,
        "diagnostics": {
            event: [*stale.get(event, []), *invalid.get(event, [])]
            for event in sorted({*invalid, *stale})
        },
        "declarationsRequired": {event: declarations[event] for event in sorted(declarations)},
        "policyVersion": ASSET_ADMISSION_POLICY_VERSION,
        "inputsSha256": _sha256(inputs),
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
    "AssetAdmissionRefused",
    "PersianAssetWorkspaceError",
    "assess_candidate_admission",
    "asset_workspace_status",
    "build_asset_manifest_from_workspace",
    "load_asset_candidate",
    "record_candidate_review",
    "record_discovery_pass",
    "reject_asset_candidate",
    "reusable_asset_candidates",
    "select_asset_candidate",
    "selection_readiness",
    "stage_asset_candidate",
    "validate_asset_manifest_against_workspace",
    "validate_edit_asset_bindings",
    "validate_edit_asset_bindings_against_manifest",
]
