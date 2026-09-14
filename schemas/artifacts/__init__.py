"""Artifact schema loading and validation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    """Load a JSON schema by artifact name."""
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_final_review_hook_quality(data: dict[str, Any]) -> None:
    """Require rendered-hook evidence only for reviews carrying the new audit."""
    metadata = data.get("metadata")
    if not isinstance(metadata, dict) or "hookQualityAudit" not in metadata:
        return

    audit = metadata.get("hookQualityAudit")
    if not isinstance(audit, dict) or str(audit.get("version") or "") != "1.0":
        raise jsonschema.ValidationError(
            "hook-quality review requires a version 1.0 hookQualityAudit"
        )
    if str(audit.get("disposition") or "") not in {"acceptable", "strong"}:
        raise jsonschema.ValidationError(
            "hook-quality review cannot pass when the preflight disposition is weak or unassessed"
        )

    review = metadata.get("hookQualityReview")
    if not isinstance(review, dict):
        raise jsonschema.ValidationError(
            "hook-quality review evidence is required when hookQualityAudit is present"
        )
    if str(review.get("version") or "") != "1.0":
        raise jsonschema.ValidationError("hook-quality review version must be 1.0")
    if str(review.get("strength") or "") not in {"acceptable", "strong"}:
        raise jsonschema.ValidationError(
            "hook-quality review strength must be acceptable or strong"
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
    if review.get("mutedHookDirectionConfirmed") is not True:
        raise jsonschema.ValidationError(
            "hook-quality review requires muted hook direction confirmation"
        )
    if str(review.get("visualVoiceAlignment") or "") not in {"acceptable", "strong"}:
        raise jsonschema.ValidationError(
            "hook-quality review visualVoiceAlignment must be acceptable or strong"
        )
    if review.get("payoffBeginsPromptly") is not True:
        raise jsonschema.ValidationError(
            "hook-quality review requires evidence that payoff begins promptly in the rendered candidate"
        )


def validate_artifact(name: str, data: dict[str, Any]) -> None:
    """Validate artifact data against its schema. Raises on failure."""
    schema = load_schema(name)
    jsonschema.validate(instance=data, schema=schema)
    if name == "final_review":
        _validate_final_review_hook_quality(data)


def list_schemas() -> list[str]:
    """List all available artifact schema names."""
    return [p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")]
