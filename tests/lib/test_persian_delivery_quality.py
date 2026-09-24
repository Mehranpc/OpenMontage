import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import lib.persian_delivery_quality as delivery
from lib.checkpoint import CheckpointValidationError, init_project, read_checkpoint
from schemas.artifacts import validate_artifact


def _candidate(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "run" / "renders" / "candidate.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"candidate")
    return path, hashlib.sha256(b"candidate").hexdigest()


def _render(path: Path, digest: str) -> dict:
    return {
        "version": "1.0",
        "outputs": [{
            "path": str(path),
            "format": "mp4",
            "resolution": "1080x1920",
            "duration_seconds": 10.0,
            "sha256": digest,
        }],
        "delivery_status": "final_candidate",
        "human_visual_approval": False,
        "persian_text_verified": False,
    }


def _review(path: Path, *, digest: str | None = None) -> dict:
    review = {
        "version": "1.0",
        "output_path": str(path),
        "status": "pass",
        "checks": {
            "technical_probe": {
                "valid_container": True,
                "issues": [],
            },
            "visual_spotcheck": {
                "frames_sampled": 4,
                "frame_paths": ["frame-1.png", "frame-2.png", "frame-3.png", "frame-4.png"],
                "black_frames_detected": False,
                "broken_overlays": False,
                "missing_assets": False,
                "unreadable_text": False,
                "issues": [],
            },
            "audio_spotcheck": {
                "unexpected_silence": False,
                "clipping_detected": False,
                "mix_intelligible": True,
                "issues": [],
            },
            "promise_preservation": {
                "delivery_promise_honored": True,
                "runtime_swap_detected": False,
                "silent_downgrade_detected": False,
                "issues": [],
            },
            "subtitle_check": {
                "subtitles_expected": False,
                "subtitles_present": False,
                "timing_drift_detected": False,
                "issues": [],
            },
        },
        "issues_found": [],
        "recommended_action": "present_to_user",
    }
    if digest is not None:
        review["output_sha256"] = digest
    return review


def _state(tmp_path: Path) -> dict:
    return {
        "project_id": "run",
        "projects_root": str(tmp_path),
        "created_at": "2026-09-24T08:00:00+00:00",
    }


def _write_inputs(tmp_path: Path, render: dict, review: dict) -> tuple[Path, Path]:
    artifacts = tmp_path / "run" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    render_path = artifacts / "render_report.json"
    review_path = artifacts / "final_review.json"
    render_path.write_text(json.dumps(render), encoding="utf-8")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return render_path, review_path


def _patch_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(delivery, "load_workflow_state", lambda *_args, **_kwargs: _state(tmp_path))
    monkeypatch.setattr(
        delivery,
        "causal_time_accounting",
        lambda *_args, **_kwargs: {
            "workflow_wall_seconds": 120.0,
            "unattributed_wall_seconds": 2.0,
            "causal_coverage_percent": 98.333,
        },
    )


def test_shadow_producer_binds_review_and_persists_quality_report(
    tmp_path: Path, monkeypatch
) -> None:
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    candidate, digest = _candidate(tmp_path)
    render_path, review_path = _write_inputs(tmp_path, _render(candidate, digest), _review(candidate))
    _patch_runtime(monkeypatch, tmp_path)

    result = delivery.stage_compose_candidate(
        "run",
        render_report_path=render_path,
        final_review_path=review_path,
        pipeline_dir=tmp_path,
        now=datetime(2026, 9, 24, 8, 2, tzinfo=timezone.utc),
    )

    report = json.loads(Path(result["quality_report_path"]).read_text(encoding="utf-8"))
    normalized_review = json.loads(review_path.read_text(encoding="utf-8"))
    validate_artifact("quality_report", report)
    assert result["policy"] == {"version": "p4-delivery-v1", "mode": "shadow"}
    assert normalized_review["output_sha256"] == digest
    assert report["output_sha256"] == digest
    assert report["technical_disposition"] == "pass"
    assert report["delivery_disposition"] == "deliver"
    assert report["time_and_cost_summary"]["causal_coverage_percent"] == 98.333
    checkpoint = read_checkpoint(tmp_path, "run", "compose")
    assert set(checkpoint["artifacts"]) >= {"render_report", "final_review", "quality_report"}


def test_enforced_producer_passes_exact_green_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENMONTAGE_PERSIAN_DELIVERY_GATE_MODE", "enforced")
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    candidate, digest = _candidate(tmp_path)
    render_path, review_path = _write_inputs(tmp_path, _render(candidate, digest), _review(candidate))
    _patch_runtime(monkeypatch, tmp_path)

    result = delivery.stage_compose_candidate(
        "run",
        render_report_path=render_path,
        final_review_path=review_path,
        pipeline_dir=tmp_path,
        now=datetime(2026, 9, 24, 8, 2, tzinfo=timezone.utc),
    )

    assert result["policy"]["mode"] == "enforced"
    assert result["delivery_disposition"] == "deliver"
    checkpoint = read_checkpoint(tmp_path, "run", "compose")
    assert checkpoint["status"] == "awaiting_human"
    assert checkpoint["artifacts"]["quality_report"]["policy_mode"] == "enforced"


def test_enforced_producer_rejects_nested_final_review_blocker(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENMONTAGE_PERSIAN_DELIVERY_GATE_MODE", "enforced")
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    candidate, digest = _candidate(tmp_path)
    review = _review(candidate)
    review["checks"]["technical_probe"]["valid_container"] = False
    render_path, review_path = _write_inputs(tmp_path, _render(candidate, digest), review)
    _patch_runtime(monkeypatch, tmp_path)

    with pytest.raises(CheckpointValidationError, match="unresolved blockers"):
        delivery.stage_compose_candidate(
            "run",
            render_report_path=render_path,
            final_review_path=review_path,
            pipeline_dir=tmp_path,
            now=datetime(2026, 9, 24, 8, 2, tzinfo=timezone.utc),
        )

    quality = json.loads(
        (tmp_path / "run" / "artifacts" / "quality_report.json").read_text(encoding="utf-8")
    )
    assert quality["technical_disposition"] == "block"
    assert "final_review.checks.technical_probe.invalid_container" in quality["blockers"]
    assert read_checkpoint(tmp_path, "run", "compose") is None


def test_legacy_project_is_not_retroactively_migrated_or_enforced(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "run"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "version": "1.0",
        "project_id": "run",
        "title": "Legacy",
        "pipeline_type": "persian-footage",
    }), encoding="utf-8")
    monkeypatch.setenv("OPENMONTAGE_PERSIAN_DELIVERY_GATE_MODE", "enforced")
    init_project("run", title="Legacy", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    candidate, digest = _candidate(tmp_path)
    render_path, review_path = _write_inputs(tmp_path, _render(candidate, digest), _review(candidate))
    _patch_runtime(monkeypatch, tmp_path)

    result = delivery.stage_compose_candidate(
        "run",
        render_report_path=render_path,
        final_review_path=review_path,
        pipeline_dir=tmp_path,
    )

    marker = json.loads((project / "project.json").read_text(encoding="utf-8"))
    checkpoint = read_checkpoint(tmp_path, "run", "compose")
    assert result["legacy_compatibility"] is True
    assert "delivery_gate_policy" not in marker
    assert result["quality_report_path"] is None
    assert "quality_report" not in checkpoint["artifacts"]
    assert set(checkpoint["artifacts"]) == {"render_report"}
