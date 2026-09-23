"""Deterministic asset-manifest and checkpoint commands for Persian production."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from lib.checkpoint import read_checkpoint, write_checkpoint
from lib.persian_asset_workspace import (
    build_asset_manifest_from_workspace,
    validate_asset_manifest_against_workspace,
)
from lib.persian_assets import assert_video_only, audit_asset_manifest
from schemas.artifacts import validate_artifact


class PersianAssetCommandError(ValueError):
    """Raised when a deterministic assets command cannot complete safely."""


def _stable_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_stable_text(value).encode("utf-8")).hexdigest()


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianAssetCommandError(f"could not read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PersianAssetCommandError(f"{label} must be a JSON object: {path}")
    return value


def _atomic_stable_json(path: Path, value: Mapping[str, Any]) -> bool:
    rendered = _stable_text(dict(value))
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
    return True


def _validate_manifest(project_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    scene_path = project_dir / "artifacts" / "scene_plan.json"
    scene_plan = (
        _read_object(scene_path, label="scene plan") if scene_path.is_file() else None
    )
    try:
        validate_artifact("asset_manifest", manifest)
        assert_video_only(manifest)
        workspace_check = validate_asset_manifest_against_workspace(project_dir, manifest)
    except Exception as exc:
        raise PersianAssetCommandError(str(exc)) from exc
    audit_problems = audit_asset_manifest(manifest, scene_plan)
    if audit_problems:
        raise PersianAssetCommandError(
            "asset manifest audit failed: " + " | ".join(audit_problems)
        )
    return workspace_check


def build_manifest(
    pipeline_dir: Path,
    project_id: str,
    *,
    video_format: str = "vertical",
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate the canonical manifest from durable selected candidates."""
    project_dir = (Path(pipeline_dir) / project_id).expanduser().resolve()
    if not project_dir.is_dir():
        raise PersianAssetCommandError(f"project does not exist: {project_dir}")
    manifest = build_asset_manifest_from_workspace(
        project_dir, video_format=video_format, overrides=overrides or {}
    )
    workspace_check = _validate_manifest(project_dir, manifest)

    manifest_path = project_dir / "artifacts" / "asset_manifest.json"
    changed = _atomic_stable_json(manifest_path, manifest)
    report = {
        "assetCount": len(manifest["assets"]),
        "auditProblems": [],
        "manifestPath": str(manifest_path),
        "manifestSha256": _digest(manifest),
        "workspaceCheck": workspace_check,
    }
    report_path = project_dir / "artifacts" / "asset_manifest.check.json"
    report_changed = _atomic_stable_json(report_path, report)
    return {
        **report,
        "changed": changed or report_changed,
        "idempotent": not changed and not report_changed,
        "reportPath": str(report_path),
    }


def write_assets_checkpoint(
    pipeline_dir: Path,
    project_id: str,
    *,
    review: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    tool_gap: str | None = None,
) -> dict[str, Any]:
    """Write the assets checkpoint once, or report an identical checkpoint as a no-op."""
    pipeline_dir = Path(pipeline_dir).expanduser().resolve()
    project_dir = pipeline_dir / project_id
    manifest_path = project_dir / "artifacts" / "asset_manifest.json"
    clean_gap = str(tool_gap or "").strip()
    status = "failed" if clean_gap else "completed"
    manifest = None
    artifacts: dict[str, Any] = {}
    if not clean_gap:
        if not manifest_path.is_file():
            raise PersianAssetCommandError(
                "canonical asset manifest is missing; run assets build-manifest first"
            )
        manifest = _read_object(manifest_path, label="canonical asset manifest")
        _validate_manifest(project_dir, manifest)
        artifacts = {"asset_manifest": manifest}

    checkpoint_metadata = dict(metadata or {})
    checkpoint_metadata.setdefault("produced_by", "persian-video assets write-checkpoint")
    if manifest is not None:
        checkpoint_metadata.setdefault("manifest", "artifacts/asset_manifest.json")
        checkpoint_metadata.setdefault("asset_count", len(manifest.get("assets") or []))
        checkpoint_metadata.setdefault("manifest_sha256", _digest(manifest))
    if clean_gap:
        checkpoint_metadata["tool_gap"] = clean_gap

    existing = read_checkpoint(pipeline_dir, project_id, "assets")
    expected_review = dict(review) if review is not None else None
    if (
        existing
        and existing.get("status") == status
        and existing.get("artifacts") == artifacts
        and existing.get("review") == expected_review
        and existing.get("metadata") == checkpoint_metadata
        and existing.get("error") == (clean_gap or None)
    ):
        return {
            "checkpointPath": str(project_dir / "checkpoint_assets.json"),
            "changed": False,
            "idempotent": True,
            "status": status,
        }

    path = write_checkpoint(
        pipeline_dir,
        project_id,
        "assets",
        status,
        artifacts,
        pipeline_type="persian-footage",
        review=expected_review,
        metadata=checkpoint_metadata,
        error=clean_gap or None,
    )
    return {
        "checkpointPath": str(path),
        "changed": True,
        "idempotent": False,
        "status": status,
    }


__all__ = [
    "PersianAssetCommandError",
    "build_manifest",
    "write_assets_checkpoint",
]
