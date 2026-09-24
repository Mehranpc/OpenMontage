"""Deterministic P4 delivery-quality producer for Persian footage runs.

This module turns the already-produced render/final-review evidence plus canonical
workflow telemetry into the strict ``quality_report`` artifact.  It deliberately
uses the existing checkpoint as the only delivery ledger: shadow runs record the
report, enforced runs are accepted/rejected by ``lib.checkpoint``'s delivery gate,
and legacy/in-flight projects without a run-start policy pin keep the old behavior.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema.exceptions import ValidationError

from lib.checkpoint import (
    PERSIAN_DELIVERY_POLICY_VERSION,
    _pinned_persian_delivery_policy,
    _render_identity,
    read_checkpoint,
    write_checkpoint,
)
from lib.paths import PROJECTS_DIR
from lib.persian_video_workflow import load_workflow_state, phase_time_accounting
from lib.persian_workflow_telemetry import causal_time_accounting
from schemas.artifacts import validate_artifact

QUALITY_REPORT_VERSION = "1.0"
QUALITY_REPORT_FILENAME = "quality_report.json"


class PersianDeliveryQualityError(ValueError):
    """Raised when delivery evidence cannot be normalized safely."""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianDeliveryQualityError(f"could not read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise PersianDeliveryQualityError(f"expected a JSON object: {path}")
    return value


def _project_file(project_root: Path, value: str | Path, *, label: str) -> Path:
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else (project_root / raw).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise PersianDeliveryQualityError(f"{label} must stay inside the project: {path}") from exc
    if not path.is_file():
        raise PersianDeliveryQualityError(f"{label} does not exist: {path}")
    return path


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> bool:
    encoded = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    temporary.replace(path)
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _list_issues(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _review_findings(
    review: Mapping[str, Any], *, output_path: str, output_sha256: str
) -> tuple[list[str], list[str], list[str]]:
    """Convert deterministic final-review facts into delivery-gate findings."""
    blockers: set[str] = set()
    stale_refs: set[str] = set()
    missing_checks: set[str] = set()

    reviewed_path = str(review.get("output_path") or "").strip()
    reviewed_sha = str(review.get("output_sha256") or "").strip().lower()
    if not reviewed_path:
        missing_checks.add("final_review.output_path")
    elif reviewed_path != output_path:
        stale_refs.add("final_review.output_path")
    if not reviewed_sha:
        missing_checks.add("final_review.output_sha256")
    elif reviewed_sha != output_sha256:
        stale_refs.add("final_review.output_sha256")

    status = str(review.get("status") or "").strip()
    if not status:
        missing_checks.add("final_review.status")
    elif status != "pass":
        blockers.add(f"final_review.status:{status}")
    action = str(review.get("recommended_action") or "").strip()
    if not action:
        missing_checks.add("final_review.recommended_action")
    elif action != "present_to_user":
        blockers.add(f"final_review.recommended_action:{action}")
    blockers.update(f"final_review.issue:{item}" for item in _list_issues(review.get("issues_found")))

    checks = review.get("checks")
    if not isinstance(checks, Mapping):
        return (
            sorted(blockers), sorted(stale_refs),
            sorted({*missing_checks, "final_review.checks"}),
        )

    required_sections = (
        "technical_probe", "visual_spotcheck", "audio_spotcheck",
        "promise_preservation", "subtitle_check",
    )
    for section in required_sections:
        value = checks.get(section)
        if not isinstance(value, Mapping):
            missing_checks.add(f"final_review.checks.{section}")
            continue
        blockers.update(
            f"final_review.checks.{section}.issue:{item}"
            for item in _list_issues(value.get("issues"))
        )

    technical = checks.get("technical_probe")
    if isinstance(technical, Mapping):
        if "valid_container" not in technical:
            missing_checks.add("final_review.checks.technical_probe.valid_container")
        elif technical.get("valid_container") is not True:
            blockers.add("final_review.checks.technical_probe.invalid_container")

    visual = checks.get("visual_spotcheck")
    if isinstance(visual, Mapping):
        sampled = visual.get("frames_sampled")
        if not isinstance(sampled, int) or isinstance(sampled, bool):
            missing_checks.add("final_review.checks.visual_spotcheck.frames_sampled")
        elif sampled < 4:
            blockers.add("final_review.checks.visual_spotcheck.insufficient_frames")
        frame_paths = visual.get("frame_paths")
        if not isinstance(frame_paths, list):
            missing_checks.add("final_review.checks.visual_spotcheck.frame_paths")
        elif len(frame_paths) < 4:
            blockers.add("final_review.checks.visual_spotcheck.insufficient_frame_paths")
        for field in (
            "black_frames_detected", "broken_overlays", "missing_assets", "unreadable_text"
        ):
            if field not in visual:
                missing_checks.add(f"final_review.checks.visual_spotcheck.{field}")
            elif visual.get(field) is not False:
                blockers.add(f"final_review.checks.visual_spotcheck.{field}")

    audio = checks.get("audio_spotcheck")
    if isinstance(audio, Mapping):
        for field, expected in (
            ("unexpected_silence", False), ("clipping_detected", False),
            ("mix_intelligible", True),
        ):
            if field not in audio:
                missing_checks.add(f"final_review.checks.audio_spotcheck.{field}")
            elif audio.get(field) is not expected:
                blockers.add(f"final_review.checks.audio_spotcheck.{field}")

    promise = checks.get("promise_preservation")
    if isinstance(promise, Mapping):
        for field, expected in (
            ("delivery_promise_honored", True), ("runtime_swap_detected", False),
            ("silent_downgrade_detected", False),
        ):
            if field not in promise:
                missing_checks.add(f"final_review.checks.promise_preservation.{field}")
            elif promise.get(field) is not expected:
                blockers.add(f"final_review.checks.promise_preservation.{field}")

    subtitle = checks.get("subtitle_check")
    if isinstance(subtitle, Mapping):
        if "subtitles_expected" not in subtitle:
            missing_checks.add("final_review.checks.subtitle_check.subtitles_expected")
        elif subtitle.get("subtitles_expected") is True and subtitle.get("subtitles_present") is not True:
            blockers.add("final_review.checks.subtitle_check.subtitles_missing")
        if "timing_drift_detected" not in subtitle:
            missing_checks.add("final_review.checks.subtitle_check.timing_drift_detected")
        elif subtitle.get("timing_drift_detected") is not False:
            blockers.add("final_review.checks.subtitle_check.timing_drift_detected")

    return sorted(blockers), sorted(stale_refs), sorted(missing_checks)


def _known_cost_usd(projects_root: Path, project_id: str) -> tuple[float, bool]:
    """Return canonical spend plus whether cost evidence was actually assessed."""
    checkpoint = read_checkpoint(projects_root, project_id, "assets")
    if not isinstance(checkpoint, Mapping):
        return 0.0, False
    snapshot = checkpoint.get("cost_snapshot")
    if isinstance(snapshot, Mapping):
        value = _number(snapshot.get("total_spent_usd"))
        if value is not None:
            return value, True
    artifacts = checkpoint.get("artifacts")
    manifest = artifacts.get("asset_manifest") if isinstance(artifacts, Mapping) else None
    if isinstance(manifest, Mapping):
        value = _number(manifest.get("total_cost_usd"))
        if value is not None:
            return value, True
    return 0.0, False


def _time_summary(
    state: Mapping[str, Any], *, now: datetime, total_cost_usd: float
) -> tuple[dict[str, float], list[str]]:
    accounting = causal_time_accounting(state, now=now, include_open=True)
    missing: list[str] = []
    if accounting is None:
        fallback = phase_time_accounting(state, now=now)
        accounting = {
            "workflow_wall_seconds": float(fallback.get("workflow_wall_seconds") or 0.0),
            "unattributed_wall_seconds": float(fallback.get("unattributed_wall_seconds") or 0.0),
            "causal_coverage_percent": 0.0,
        }
        missing.append("telemetry.causal_accounting")
    return {
        "workflow_wall_seconds": float(accounting.get("workflow_wall_seconds") or 0.0),
        "unattributed_wall_seconds": float(accounting.get("unattributed_wall_seconds") or 0.0),
        "causal_coverage_percent": float(accounting.get("causal_coverage_percent") or 0.0),
        "total_cost_usd": float(total_cost_usd),
    }, missing


def build_quality_report(
    state: Mapping[str, Any],
    render_report: Mapping[str, Any],
    final_review: Mapping[str, Any],
    *,
    policy: tuple[str, str],
    projects_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one strict report from canonical evidence; never infer a pass from absence."""
    effective_now = now or datetime.now(timezone.utc)
    if effective_now.tzinfo is None:
        raise PersianDeliveryQualityError("quality report timestamp must be timezone-aware")
    project_id = str(state.get("project_id") or "").strip()
    if not project_id:
        raise PersianDeliveryQualityError("workflow state is missing project_id")
    output_path, output_sha256 = _render_identity(
        dict(render_report), projects_root, project_id
    )
    blockers, stale_refs, missing_checks = _review_findings(
        final_review, output_path=output_path, output_sha256=output_sha256
    )
    total_cost_usd, cost_assessed = _known_cost_usd(projects_root, project_id)
    time_summary, telemetry_missing = _time_summary(
        state,
        now=effective_now,
        total_cost_usd=total_cost_usd,
    )
    cost_missing = [] if cost_assessed else ["cost.total_spent_usd"]
    missing_checks = sorted({*missing_checks, *telemetry_missing, *cost_missing})
    clean = not blockers and not stale_refs and not missing_checks
    report = {
        "version": QUALITY_REPORT_VERSION,
        "policy_version": policy[0],
        "policy_mode": policy[1],
        "generated_at": effective_now.isoformat(),
        "output_path": output_path,
        "output_sha256": output_sha256,
        "technical_disposition": "pass" if clean else "block",
        "delivery_disposition": "deliver" if clean else "block",
        "blockers": blockers,
        "stale_refs": stale_refs,
        "missing_checks": missing_checks,
        "time_and_cost_summary": time_summary,
    }
    try:
        validate_artifact("quality_report", report)
    except ValidationError as exc:
        raise PersianDeliveryQualityError(f"quality_report failed schema: {exc.message}") from exc
    return report


def _normalize_final_review(
    review: Mapping[str, Any], *, output_path: str, output_sha256: str
) -> dict[str, Any]:
    normalized = dict(review)
    reviewed_path = str(normalized.get("output_path") or "").strip()
    if reviewed_path == output_path and not str(normalized.get("output_sha256") or "").strip():
        normalized["output_sha256"] = output_sha256
    return normalized


def stage_compose_candidate(
    project_id: str,
    *,
    render_report_path: str | Path,
    final_review_path: str | Path,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Produce delivery evidence and stage the exact compose candidate for the human gate."""
    projects_root = Path(pipeline_dir or PROJECTS_DIR).resolve()
    state = load_workflow_state(project_id, pipeline_dir=projects_root)
    project_root = (projects_root / project_id).resolve()
    report_path = _project_file(project_root, render_report_path, label="render_report")
    review_path = _project_file(project_root, final_review_path, label="final_review")
    render_report = _read_json_object(report_path)
    final_review = _read_json_object(review_path)

    marker_path = project_root / "project.json"
    marker = _read_json_object(marker_path)
    policy = _pinned_persian_delivery_policy(marker)

    # Existing/in-flight projects intentionally remain on their pre-P4 contract.
    if policy is None:
        checkpoint_path = write_checkpoint(
            projects_root, project_id, "compose", "awaiting_human",
            {"render_report": render_report, "final_review": final_review}, pipeline_type="persian-footage",
        )
        return {
            "project_id": project_id,
            "legacy_compatibility": True,
            "checkpoint_path": str(checkpoint_path),
            "quality_report_path": None,
            "policy": None,
        }

    if policy[0] != PERSIAN_DELIVERY_POLICY_VERSION:
        raise PersianDeliveryQualityError(f"unsupported delivery policy: {policy[0]}")
    try:
        validate_artifact("render_report", render_report)
    except ValidationError as exc:
        raise PersianDeliveryQualityError(f"render_report failed schema: {exc.message}") from exc

    output_path, output_sha256 = _render_identity(render_report, projects_root, project_id)
    normalized_review = _normalize_final_review(
        final_review, output_path=output_path, output_sha256=output_sha256
    )
    try:
        validate_artifact("final_review", normalized_review)
    except ValidationError as exc:
        raise PersianDeliveryQualityError(f"final_review failed schema: {exc.message}") from exc
    review_changed = _write_json_atomic(review_path, normalized_review)

    quality_report = build_quality_report(
        state, render_report, normalized_review,
        policy=policy, projects_root=projects_root, now=now,
    )
    quality_path = project_root / "artifacts" / QUALITY_REPORT_FILENAME
    quality_changed = _write_json_atomic(quality_path, quality_report)
    checkpoint_path = write_checkpoint(
        projects_root,
        project_id,
        "compose",
        "awaiting_human",
        {
            "render_report": render_report,
            "final_review": normalized_review,
            "quality_report": quality_report,
        },
        pipeline_type="persian-footage",
        human_approval_required=True,
        human_approved=False,
        cost_snapshot={"total_spent_usd": quality_report["time_and_cost_summary"]["total_cost_usd"]},
        metadata={
            "delivery_policy_version": policy[0],
            "delivery_policy_mode": policy[1],
            "quality_report_path": str(quality_path),
            "quality_report_sha256": _sha256(quality_path),
            "final_review_path": str(review_path),
            "final_review_sha256": _sha256(review_path),
        },
    )
    return {
        "project_id": project_id,
        "legacy_compatibility": False,
        "policy": {"version": policy[0], "mode": policy[1]},
        "checkpoint_path": str(checkpoint_path),
        "quality_report_path": str(quality_path),
        "quality_report_sha256": _sha256(quality_path),
        "quality_report_changed": quality_changed,
        "final_review_path": str(review_path),
        "final_review_sha256": _sha256(review_path),
        "final_review_changed": review_changed,
        "technical_disposition": quality_report["technical_disposition"],
        "delivery_disposition": quality_report["delivery_disposition"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persian-delivery-quality")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser(
        "stage-candidate",
        help="produce quality_report and stage the digest-bound compose candidate",
    )
    stage.add_argument("project_id")
    stage.add_argument("--render-report-json", required=True, metavar="PATH")
    stage.add_argument("--final-review-json", required=True, metavar="PATH")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "stage-candidate":
            result = stage_compose_candidate(
                args.project_id,
                render_report_path=args.render_report_json,
                final_review_path=args.final_review_json,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PersianDeliveryQualityError",
    "QUALITY_REPORT_VERSION",
    "build_quality_report",
    "stage_compose_candidate",
]
