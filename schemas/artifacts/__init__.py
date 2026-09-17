"""Artifact schema loading, contract discovery, and validation utilities."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import jsonschema

SCHEMA_DIR = Path(__file__).parent

ARTIFACT_NAMES = [
    "research_brief",
    "proposal_packet",
    "brief",
    "script",
    "character_design",
    "rig_plan",
    "pose_library",
    "scene_plan",
    "action_timeline",
    "asset_manifest",
    "edit_decisions",
    "render_report",
    "publish_log",
    "post_publish_performance",
    "review",
    "cost_log",
    "decision_log",
    "source_media_review",
    "final_review",
    "character_qa_report",
    "video_analysis_brief",
]


def load_schema(name: str) -> dict:
    """Load the single machine-readable contract for an artifact."""
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def artifact_contract(name: str) -> dict[str, Any]:
    """Expose validator/builder/CLI metadata derived only from the JSON schema.

    Agents and CLIs can inspect this compact representation instead of reading
    Python validator source to discover required fields.
    """
    schema = load_schema(name)
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = [str(item) for item in schema.get("required") or []]
    rows: list[str] = []
    for field in required:
        definition = properties.get(field) if isinstance(properties.get(field), dict) else {}
        kind = definition.get("type") or "value"
        description = str(definition.get("description") or "").strip()
        rows.append(f"--{field.replace('_', '-')} <{kind}>" + (f" — {description}" if description else ""))
    return {
        "name": name,
        "schemaPath": str((SCHEMA_DIR / f"{name}.schema.json").resolve()),
        "schemaVersion": schema.get("$schema"),
        "title": schema.get("title") or name,
        "description": schema.get("description") or "",
        "requiredFields": required,
        "properties": deepcopy(properties),
        "cliHelp": rows or ["No top-level required fields."],
    }


def build_artifact(name: str, values: Mapping[str, Any] | None = None, /, **fields: Any) -> dict[str, Any]:
    """Build and validate an artifact from the same schema used at runtime."""
    if values is not None and not isinstance(values, Mapping):
        raise TypeError("artifact values must be a mapping")
    payload = dict(values or {})
    overlap = set(payload).intersection(fields)
    if overlap:
        raise ValueError("artifact fields supplied twice: " + ", ".join(sorted(overlap)))
    payload.update(fields)
    validate_artifact(name, payload)
    return payload


def _validate_final_review_hook_quality(data: dict[str, Any]) -> None:
    """Validate rendered-hook evidence while preserving failed-review evidence."""
    metadata = data.get("metadata")
    if not isinstance(metadata, dict) or "hookQualityAudit" not in metadata:
        return

    audit = metadata.get("hookQualityAudit")
    if not isinstance(audit, dict):
        raise jsonschema.ValidationError("hook-quality review requires hookQualityAudit evidence")
    audit_version = str(audit.get("version") or "")
    if audit_version not in {"1.0", "2.0"}:
        raise jsonschema.ValidationError("hook-quality audit version must be 1.0 or 2.0")
    audit_disposition = str(audit.get("disposition") or "")
    if audit_disposition not in {"weak", "acceptable", "strong", "unassessed"}:
        raise jsonschema.ValidationError("hook-quality audit disposition is invalid")

    review = metadata.get("hookQualityReview")
    if not isinstance(review, dict):
        raise jsonschema.ValidationError(
            "hook-quality review evidence is required when hookQualityAudit is present"
        )

    if audit_version == "2.0":
        from lib.persian_rendered_review import (
            PersianRenderedReviewError,
            validate_rendered_hook_review,
        )

        try:
            validate_rendered_hook_review(
                review,
                candidate_sha256=str(review.get("reviewedCandidateSha256") or ""),
                require_pass=data.get("status") == "pass",
            )
        except PersianRenderedReviewError as exc:
            raise jsonschema.ValidationError(str(exc)) from exc
        return

    if str(review.get("version") or "") != "1.0":
        raise jsonschema.ValidationError("hook-quality review version must be 1.0")
    strength = str(review.get("strength") or "")
    if strength not in {"weak", "acceptable", "strong"}:
        raise jsonschema.ValidationError(
            "hook-quality review strength must be weak, acceptable, or strong"
        )
    if not str(review.get("rationale") or "").strip():
        raise jsonschema.ValidationError("hook-quality review requires a non-empty rationale")

    observations = review.get("observations")
    if (
        not isinstance(observations, list)
        or len(observations) < 2
        or any(not isinstance(item, str) or not item.strip() for item in observations)
    ):
        raise jsonschema.ValidationError(
            "hook-quality review requires at least two non-empty rendered-opening observations"
        )
    muted_confirmed = review.get("mutedHookDirectionConfirmed")
    payoff_prompt = review.get("payoffBeginsPromptly")
    if not isinstance(muted_confirmed, bool):
        raise jsonschema.ValidationError(
            "hook-quality review mutedHookDirectionConfirmed must be boolean"
        )
    if not isinstance(payoff_prompt, bool):
        raise jsonschema.ValidationError(
            "hook-quality review payoffBeginsPromptly must be boolean"
        )
    visual_alignment = str(review.get("visualVoiceAlignment") or "")
    if visual_alignment not in {"weak", "acceptable", "strong"}:
        raise jsonschema.ValidationError(
            "hook-quality review visualVoiceAlignment must be weak, acceptable, or strong"
        )

    if data.get("status") == "pass":
        if audit_disposition not in {"acceptable", "strong"}:
            raise jsonschema.ValidationError(
                "passing hook review requires acceptable or strong preflight disposition"
            )
        if strength not in {"acceptable", "strong"}:
            raise jsonschema.ValidationError(
                "passing hook-quality review strength must be acceptable or strong"
            )
        if muted_confirmed is not True:
            raise jsonschema.ValidationError(
                "passing hook-quality review requires muted hook direction confirmation"
            )
        if visual_alignment not in {"acceptable", "strong"}:
            raise jsonschema.ValidationError(
                "passing hook-quality review visualVoiceAlignment must be acceptable or strong"
            )
        if payoff_prompt is not True:
            raise jsonschema.ValidationError(
                "passing hook-quality review requires prompt payoff in the rendered candidate"
            )


def _parse_observed_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise jsonschema.ValidationError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise jsonschema.ValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise jsonschema.ValidationError(f"{label} must include a timezone offset")
    return parsed


def _validate_post_publish_performance(data: dict[str, Any]) -> None:
    published_at = _parse_observed_timestamp(data.get("published_at"), label="published_at")
    seen_checkpoints: set[str] = set()
    previous_hours = -1.0
    previous_captured: datetime | None = None
    for index, snapshot in enumerate(data.get("snapshots") or []):
        if not isinstance(snapshot, dict):
            continue
        checkpoint = str(snapshot.get("checkpoint") or "")
        if checkpoint in seen_checkpoints:
            raise jsonschema.ValidationError(f"duplicate post-publish checkpoint {checkpoint!r}")
        seen_checkpoints.add(checkpoint)
        captured = _parse_observed_timestamp(
            snapshot.get("captured_at"), label=f"snapshots[{index}].captured_at"
        )
        if captured < published_at:
            raise jsonschema.ValidationError("post-publish snapshot cannot precede published_at")
        hours = float(snapshot.get("hours_since_publish") or 0.0)
        actual_hours = (captured - published_at).total_seconds() / 3600.0
        if abs(hours - actual_hours) > 0.25:
            raise jsonschema.ValidationError(
                f"snapshots[{index}].hours_since_publish is inconsistent with captured_at"
            )
        if hours <= previous_hours:
            raise jsonschema.ValidationError("post-publish snapshot hours must increase")
        if previous_captured is not None and captured <= previous_captured:
            raise jsonschema.ValidationError("post-publish captured_at timestamps must increase")
        previous_hours = hours
        previous_captured = captured


def validate_artifact(name: str, data: dict[str, Any]) -> None:
    """Validate artifact data against its schema. Raises on failure."""
    schema = load_schema(name)
    jsonschema.validate(instance=data, schema=schema)
    if name == "final_review":
        _validate_final_review_hook_quality(data)
    elif name == "post_publish_performance":
        _validate_post_publish_performance(data)


def list_schemas() -> list[str]:
    """List all available artifact schema names."""
    return [p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")]
